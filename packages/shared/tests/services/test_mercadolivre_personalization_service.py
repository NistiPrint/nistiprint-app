import unittest
from unittest.mock import patch

from scripts import backfill_mercadolivre_chat as chat_backfill
from nistiprint_shared.services import mercadolivre_personalization_service as service
from nistiprint_shared.services import ai_personalization_account_config as account_config
from nistiprint_shared.services.platform_drivers import mercadolivre as driver


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.filters.append((key, set(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def range(self, *_args):
        return self

    def execute(self):
        rows = [row for row in self.rows if all(
            row.get(key) in value if isinstance(value, set) else row.get(key) == value
            for key, value in self.filters
        )]
        return FakeResponse(rows)


class FakeDatabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.get(name, []))


class PedidosSchemaQuery(FakeQuery):
    def select(self, columns, **kwargs):
        if "data_pedido" in columns.split(","):
            raise AssertionError("pedidos does not have a data_pedido column")
        return super().select(columns, **kwargs)


class PedidosSchemaDatabase(FakeDatabase):
    def table(self, name):
        query = PedidosSchemaQuery(self.tables.get(name, [])) if name == "pedidos" else FakeQuery(self.tables.get(name, []))
        return query


class MercadoLivrePersonalizationTests(unittest.TestCase):
    def test_shared_inbox_consumer_uses_each_webhook_integration(self):
        accounts = [
            {"integration_id": 7, "seller_id": "seller-a", "application_id": "app-a",
             "module_id": "mercadolivre", "app_profile_id": 10},
            {"integration_id": 8, "seller_id": "seller-b", "application_id": "app-b",
             "module_id": "mercadolivre", "app_profile_id": 11},
        ]
        entries = [
            {"id": 101, "marketplace_integration_id": 7, "provider_message_id": "msg-a",
             "raw_payload": {"actions": ["created"]}, "attempts": 1},
            {"id": 102, "marketplace_integration_id": 8, "provider_message_id": "msg-b",
             "raw_payload": {"actions": ["created"]}, "attempts": 1},
        ]
        integrations = {
            7: {"id": 7, "config": {"account_identifiers": {"primary": "seller-a"}}},
            8: {"id": 8, "config": {"account_identifiers": {"primary": "seller-b"}}},
        }
        syncs = []
        provider_requests = []

        def provider_request(integration_id, _endpoint, function, integration, message_id):
            provider_requests.append((integration_id, integration["id"]))
            return {"message_resources": [
                {"name": "packs", "id": f"pack-{integration_id}"},
                {"name": "seller", "id": f"seller-{ 'a' if integration_id == 7 else 'b' }"},
            ]}

        with patch.object(service, "message_consumer_accounts", return_value=accounts), \
             patch.object(service, "_resolve_unmatched_for_account") as resolve_unmatched, \
             patch.object(service, "_claim_notifications", return_value=entries) as claim, \
             patch.object(service, "_integration", side_effect=lambda ident: integrations[ident]), \
             patch.object(service, "_meli_request", side_effect=provider_request), \
             patch.object(service, "sync_pack", side_effect=lambda *args, **kwargs: syncs.append((args, kwargs))), \
             patch.object(service, "supabase_db"):
            result = service.process_inbox_once(limit=10)

        self.assertEqual(result, {"claimed": 2, "synced": 2, "retried": 0, "failed": 0})
        self.assertEqual(claim.call_args.args[0], [7, 8])
        self.assertEqual([call.args[0] for call in resolve_unmatched.call_args_list], [7, 8])
        self.assertEqual([row[0][0] for row in syncs], [7, 8])
        self.assertEqual([row[0][1] for row in syncs], ["pack-7", "pack-8"])
        self.assertEqual(provider_requests, [(7, 7), (8, 8)])

    def test_personalization_reads_persisted_chat_without_running_message_ingest(self):
        database = FakeDatabase({"mercadolivre_chat_conversations": [{
            "marketplace_integration_id": 7, "pack_id": "pack-7", "seller_id": "seller-a",
            "raw_json": {}, "context_hash": "same-context", "ai_status": "success",
        }]})
        with patch.object(service, "_integration", return_value={}), \
             patch.object(service, "_settings", return_value={}), \
             patch.object(service, "_pack_context",
                          return_value=([], [], "same-context", False)), \
             patch.object(service, "sync_pack") as sync_pack, \
             patch.object(service, "supabase_db", database):
            result = service.process_pack(7, "pack-7")
        self.assertEqual(result, {"status": "up_to_date", "pack_id": "pack-7"})
        sync_pack.assert_not_called()

    def test_mercadolivre_request_limiter_is_scoped_to_each_integration(self):
        from nistiprint_shared.services import mercadolivre_rate_limit as rate_limit
        with patch.object(rate_limit.mercadolivre_rate_limit_coordinator, "acquire") as acquire:
            self.assertEqual(service._meli_request(7, "messages", lambda: "a"), "a")
            self.assertEqual(service._meli_request(8, "messages", lambda: "b"), "b")
        self.assertEqual(acquire.call_args_list[0].args, (7, "messages"))
        self.assertEqual(acquire.call_args_list[1].args, (8, "messages"))

    def test_pack_metadata_404_does_not_block_conversation_ingest(self):
        integration = {"id": 7}
        with patch.object(service, "_meli_request", return_value={
            "error": "Erro na API Mercado Livre: 404", "status_code": 404,
            "retryable": False,
        }):
            self.assertEqual(service._pack_order_ids(7, integration, "2000018727299206"), [])

    def test_sync_pack_persists_messages_when_optional_pack_lookup_returns_404(self):
        from unittest.mock import MagicMock
        integration = {"id": 7}
        fetched_endpoints = []
        message_rows = [{"provider_message_id": "message-from-unread",
                         "sender_role": "buyer", "text_content": "Olá", "attachments": []}]

        def provider_request(_integration_id, endpoint, _function, _integration, *_args, **_kwargs):
            fetched_endpoints.append(endpoint)
            if endpoint == "packs":
                return {"error": "Erro na API Mercado Livre: 404", "status_code": 404,
                        "retryable": False}
            if endpoint == "orders":
                return {"error": "Erro na API Mercado Livre: 404", "status_code": 404,
                        "retryable": False}
            return {"messages": [{"id": "message-from-unread", "text": "Olá"}],
                    "paging": {"total": 1}}

        database = MagicMock()
        database.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        with patch.object(service, "_integration", return_value=integration), \
             patch.object(service, "_meli_request", side_effect=provider_request), \
             patch.object(service, "_upsert_messages", return_value=message_rows), \
             patch.object(service, "_mark_inbox_messages_persisted") as mark_persisted, \
             patch.object(service, "supabase_db", database):
            result = service.sync_pack(7, "2000018727299206", "seller-7")

        self.assertEqual(result["messages"], 1)
        self.assertIn("packs", fetched_endpoints)
        self.assertIn("messages", fetched_endpoints)
        mark_persisted.assert_called_once_with(7, message_rows)

    def test_persisted_reconciliation_messages_complete_matching_inbox_rows(self):
        from unittest.mock import MagicMock
        database = MagicMock()
        with patch.object(service, "supabase_db", database):
            service._mark_inbox_messages_persisted(7, [
                {"provider_message_id": "message-a"},
                {"provider_message_id": "message-a"},
                {"provider_message_id": "message-b"},
                {"provider_message_id": None},
            ])
        database.table.assert_called_once_with("mercadolivre_chat_inbox")
        query = database.table.return_value.update.return_value
        query.eq.assert_called_once_with("marketplace_integration_id", 7)
        scoped_query = query.eq.return_value
        self.assertEqual(scoped_query.in_.call_args_list[0].args,
                         ("provider_message_id", ["message-a", "message-b"]))
        self.assertEqual(scoped_query.in_.return_value.in_.call_args.args,
                         ("status", ["pending", "retry", "processing"]))
        scoped_query.in_.return_value.in_.return_value.execute.assert_called_once_with()

    def test_shared_account_config_exposes_and_updates_meli_daily_schedule(self):
        installation = {"id": 7, "module_id": "mercadolivre"}
        raw = {"schedule_enabled": False, "schedule_hour": 8, "schedule_minute": 35}
        with patch.object(account_config, "_installation", return_value=installation), \
             patch("nistiprint_shared.services.mercadolivre_personalization_service._settings", return_value=raw):
            config = account_config.get_config(7)
        self.assertFalse(config["schedule_enabled"])
        self.assertEqual((config["schedule_hour"], config["schedule_minute"]), (8, 35))

        current = {"marketplace": "mercadolivre", "provider": "gemini", "model_name": "gemini-2.5-flash",
                   "fallback_provider": "", "timeout_seconds": 60, "max_processing": 50,
                   "prompt_template": "A prompt longer than the minimum length."}
        with patch.object(account_config, "_installation", return_value=installation), \
             patch.object(account_config, "get_config", return_value=current), \
             patch("nistiprint_shared.services.ai.router.build_provider"), \
             patch("nistiprint_shared.services.mercadolivre_personalization_service.update_settings") as save:
            account_config.update_config(7, {"schedule_enabled": False, "schedule_hour": 8,
                                             "schedule_minute": 35})
        save.assert_called_once()
        self.assertEqual({key: save.call_args.args[1][key] for key in
                          ("schedule_enabled", "schedule_hour", "schedule_minute")},
                         {"schedule_enabled": False, "schedule_hour": 8, "schedule_minute": 35})

    def test_shopee_account_config_rejects_meli_schedule_fields(self):
        with patch.object(account_config, "_installation", return_value={"id": 8, "module_id": "shopee"}), \
             patch.object(account_config, "get_config", return_value={
                 "marketplace": "shopee", "provider": "gemini", "model_name": "gemini-2.5-flash",
                 "fallback_provider": "", "timeout_seconds": 60, "max_processing": 50,
             }):
            with self.assertRaisesRegex(ValueError, "somente para Mercado Livre"):
                account_config.update_config(8, {"schedule_enabled": False})

    def test_order_queries_use_the_canonical_data_venda_column(self):
        order = {
            "id": 10, "numero_pedido": "ML-10", "codigo_pedido_externo": "external-10",
            "marketplace_order_id": "external-10", "marketplace_integration_id": 7,
            "data_venda": "2026-10-06T09:00:00", "situacao_pedido_id": 2,
            "cliente_nome": "Cliente", "buyer_username": "buyer-10",
            "informacoes_cliente": {}, "message_to_seller": None,
        }
        database = PedidosSchemaDatabase({
            "pedidos": [order],
            "itens_pedido": [{"id": 20, "pedido_id": 10, "personalizado": True}],
        })
        with patch.object(service, "_integration", return_value={}), \
             patch.object(service, "supabase_db", database):
            listed = service.list_personalized_orders(7)
            context_orders = service._integration_orders(7, ["external-10"])
        self.assertEqual(listed[0]["id"], 10)
        self.assertEqual(context_orders[0]["id"], 10)

    def test_message_api_keeps_opaque_ids_and_does_not_mark_history_read(self):
        result = {"message_id": "0033b582a1474fa98c02d229abcec43c"}
        captured = []

        class DriverResponse:
            def to_legacy(self):
                return result

        integration = {"access_token": "token"}
        with patch.object(driver, "_auth_headers", return_value={"Authorization": "Bearer token"}), \
             patch.object(driver, "request_json", side_effect=lambda *args, **kwargs:
                          captured.append((args, kwargs)) or DriverResponse()):
            message = driver.get_message(integration, result["message_id"])
            page = driver.get_post_sale_messages(integration, "2000000089077943", "415458330")
        self.assertEqual(message["message_id"], result["message_id"])
        self.assertEqual(page, result)
        self.assertIn(result["message_id"], captured[0][0][1])
        self.assertEqual(captured[1][1]["params"]["mark_as_read"], "false")
        self.assertEqual(captured[1][1]["params"]["tag"], "post_sale")

    def test_pack_order_ids_normalize_objects_scalars_and_duplicates(self):
        with patch.object(service, "_meli_request", return_value={"orders": [
            {"id": 2000018837650802, "static_tags": []},
            {"id": "2000018837650802"},
            2000018835141756,
        ]}):
            self.assertEqual(service._pack_order_ids(7, {}, "pack-1"),
                             ["2000018837650802", "2000018835141756"])

    def test_pack_order_ids_reject_malformed_entries(self):
        with patch.object(service, "_meli_request", return_value={
            "orders": [{"static_tags": []}],
        }):
            with self.assertRaisesRegex(ValueError, "ID válido"):
                service._pack_order_ids(7, {}, "pack-1")

    def test_backfill_safely_normalizes_legacy_object_ids(self):
        self.assertEqual(chat_backfill._conversation_order_ids([
            "{'id': 2000018837650802, 'static_tags': []}",
            "{'id': '2000018837650802'}",
        ]), ["2000018837650802"])
        self.assertEqual(chat_backfill._conversation_order_ids(["2000018835141756"]),
                         ["2000018835141756"])
        self.assertEqual(chat_backfill._legacy_value("__import__('os').system('whoami')"),
                         "__import__('os').system('whoami')")

    def test_backfill_recovers_nested_message_creation_date(self):
        self.assertEqual(chat_backfill._message_timestamp({
            "message_date": {"created": "2026-10-05T10:53:40Z"},
        }), "2026-10-05T10:53:40+00:00")
        self.assertEqual(chat_backfill._message_timestamp({
            "date_created": "2026-10-05T11:00:00Z",
        }), "2026-10-05T11:00:00+00:00")
        self.assertIsNone(chat_backfill._message_timestamp({}))

    def test_message_normalization_reads_created_date_and_attachment_fields(self):
        tables = {}
        with patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            rows = service._upsert_messages(7, "pack-1", "seller-1", [
                {"id": "meli-message-1", "from": {"user_id": "seller-1"},
                 "message_date": {"created": "2026-10-05T10:53:40Z"},
                 "message_attachments": [{"type": "image", "filename": "foto.jpg"}],
                 "moderation": {"status": "available"}},
                {"id": "meli-message-2", "date_created": "2026-10-05T11:00:00Z"},
                {"id": "meli-message-3", "date": "2026-10-05T11:10:00Z"},
                {"id": "meli-message-4"},
            ], None)

        self.assertEqual(rows[0]["created_at"], "2026-10-05T10:53:40+00:00")
        self.assertEqual(rows[0]["attachments"][0]["filename"], "foto.jpg")
        self.assertEqual(rows[0]["moderation_status"], "available")
        self.assertEqual(rows[1]["created_at"], "2026-10-05T11:00:00+00:00")
        self.assertEqual(rows[2]["created_at"], "2026-10-05T11:10:00+00:00")
        self.assertIsNone(rows[3]["created_at"])

    def test_sender_not_assumed_to_be_buyer_because_recipient_is_seller(self):
        tables = {}
        with patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            rows = service._upsert_messages(7, "pack-1", "seller-1", [
                {"message_id": "agent-msg", "from": {"user_id": "3037675074"},
                 "to": {"user_id": "seller-1"}, "text": {"plain": "Nome Alice"}},
                {"message_id": "unknown-msg", "from": {"user_id": "someone-else"},
                 "to": {"user_id": "seller-1"}, "text": {"plain": "Nome Alice"}},
                {"message_id": "buyer-msg", "from": {"user_id": "buyer-1"},
                 "to": {"user_id": "seller-1"}, "text": {"plain": "Nome Alice"}},
            ], None, buyer_ids={"buyer-1"})
        self.assertEqual([row["sender_role"] for row in rows], ["agent", "unknown", "buyer"])

    def test_opaque_webhook_message_id_is_extracted_from_resource_path(self):
        tables = {}
        with patch.object(service, "_notification_account_candidates", return_value=(7, 7)), \
             patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            result = service.enqueue_notification({
                "topic": "messages", "user_id": 123, "application_id": 456,
                "resource": "/messages/0033b582a1474fa98c02d229abcec43c",
                "actions": ["created"], "_id": "delivery-1",
            }, webhook_event_id=99)
        self.assertEqual(result["resource_id"], "0033b582a1474fa98c02d229abcec43c")
        stored = tables["mercadolivre_chat_inbox"][0]
        self.assertEqual(stored["provider_message_id"], result["resource_id"])
        self.assertEqual(stored["marketplace_integration_id"], 7)
        self.assertTrue(stored["dedupe_key"])

    def test_full_mercado_livre_message_resource_is_reduced_to_opaque_id(self):
        tables = {}
        with patch.object(service, "_notification_account_candidates", return_value=(7, 7)), \
             patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            result = service.enqueue_notification({
                "topic": "messages", "user_id": 207584268,
                "application_id": 2056757525653794,
                "resource": "https://api.mercadolibre.com/messages/01a1140382b276859b6048108d33a481?foo=bar",
                "actions": ["created"], "_id": "9b15a226-9c9a-4a4f-862d-823564cf8301",
            }, webhook_event_id=102)
        self.assertEqual(result["resource_id"], "01a1140382b276859b6048108d33a481")
        stored = tables["mercadolivre_chat_inbox"][0]
        self.assertEqual(stored["status"], "pending")
        self.assertEqual(stored["marketplace_integration_id"], 7)

    def test_missing_webhook_identity_is_saved_as_unmatched_audit_item(self):
        tables = {}
        with patch.object(service, "_notification_account_candidates", return_value=(None, 7)), \
             patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            result = service.enqueue_notification({
                "topic": "messages", "user_id": 123,
                "resource": "/messages/opaque-message-id", "actions": ["created"],
            }, webhook_event_id=100)
        saved = tables["mercadolivre_chat_inbox"][0]
        self.assertEqual(result["identity_status"], "unmatched")
        self.assertIsNone(saved["application_id"])
        self.assertEqual(saved["marketplace_integration_id"], 7)
        self.assertEqual(saved["status"], "unmatched")
        self.assertFalse(saved["raw_payload"]["_identity_complete"])

    def test_invalid_message_resource_is_audited_instead_of_sent_to_provider(self):
        tables = {}
        with patch.object(service, "_notification_account_candidates", return_value=(7, 7)), \
             patch.object(service.supabase_db, "table", side_effect=lambda name: CaptureQuery(tables, name)):
            result = service.enqueue_notification({
                "topic": "messages", "user_id": "seller-1", "application_id": "app-1",
                "resource": "/messages/", "actions": ["created"],
            }, webhook_event_id=101)
        saved = tables["mercadolivre_chat_inbox"][0]
        self.assertEqual(result["identity_status"], "unmatched")
        self.assertTrue(saved["provider_message_id"].startswith("unresolved-"))
        self.assertFalse(saved["raw_payload"]["_resource_valid"])

    def test_application_id_comes_from_this_profiles_encrypted_client_id(self):
        fake_db = FakeDatabase({"integration_app_profiles": [
            {"id": 14, "module_id": "mercadolivre", "is_active": True},
            {"id": 15, "module_id": "shopee", "is_active": True},
            {"id": 16, "module_id": "mercadolivre", "is_active": False},
        ]})
        with patch.object(service, "supabase_db", fake_db), \
             patch("nistiprint_shared.services.integration_secret_service.integration_secret_service.get_secret_map",
                   side_effect=lambda owner, profile_id: {"client_id": f"app-{profile_id}"}):
            self.assertEqual(service._profile_application_id(14, "mercadolivre"), "app-14")
            self.assertIsNone(service._profile_application_id(15, "mercadolivre"))
            self.assertIsNone(service._profile_application_id(16, "mercadolivre"))

    def test_two_connected_accounts_are_resolved_by_both_webhook_identities(self):
        tables = {
            "integration_modules": [{"id": "mercadolivre"}],
            "installed_integrations": [
                {"id": 7, "module_id": "mercadolivre", "is_active": True,
                 "config": {"account_identifiers": {"primary": "seller-a"}}, "app_profile_id": 10},
                {"id": 8, "module_id": "mercadolivre", "is_active": True,
                 "config": {"account_identifiers": {"primary": "seller-b"}}, "app_profile_id": 11},
            ],
            "integration_app_profiles": [
                {"id": 10, "module_id": "mercadolivre", "is_active": True},
                {"id": 11, "module_id": "mercadolivre", "is_active": True},
            ],
        }
        with patch.object(service, "supabase_db", FakeDatabase(tables)), \
             patch("nistiprint_shared.services.integration_secret_service.integration_secret_service.get_secret_map",
                   side_effect=lambda owner, profile_id: {
                       "client_id": "app-a" if profile_id == 10 else "app-b"}):
            self.assertEqual(service._notification_account_candidates("seller-b", "app-b"), (8, 8))
            self.assertEqual(service._notification_account_candidates("seller-a", "app-b"), (None, None))
            self.assertEqual(service._notification_account_candidates("seller-a", None), (None, 7))

    def test_shared_oauth_app_still_selects_the_account_by_seller_identity(self):
        tables = {
            "integration_modules": [{"id": "mercadolivre"}],
            "installed_integrations": [
                {"id": 7, "module_id": "mercadolivre", "is_active": True,
                 "config": {"user_id": "seller-a"}, "app_profile_id": 10},
                {"id": 8, "module_id": "mercadolivre", "is_active": True,
                 "config": {"user_id": "seller-b"}, "app_profile_id": 10},
            ],
            "integration_app_profiles": [
                {"id": 10, "module_id": "mercadolivre", "is_active": True},
            ],
        }
        with patch.object(service, "supabase_db", FakeDatabase(tables)), \
             patch("nistiprint_shared.services.integration_secret_service.integration_secret_service.get_secret_map",
                   return_value={"client_id": "shared-app"}):
            self.assertEqual(service._notification_account_candidates("seller-b", "shared-app"), (8, 8))

    def test_print_rows_require_current_context_and_exact_internal_account(self):
        integration_id, pedido_id, item_id = 7, 101, 201
        message = {"provider_message_id": "msg-1", "sender_role": "buyer",
                   "text_content": "Duas unidades: Ana e Bia", "created_at": "2026-10-01T10:00:00+00:00",
                   "moderation_status": "available", "attachments": []}
        context_hash = service._context_hash([message])
        base = {"marketplace_integration_id": integration_id, "pedido_id": pedido_id,
                "item_pedido_id": item_id, "pack_id": "pack-1", "status": "SUCCESS",
                "confirmed": False, "source": "ai", "provider_message_id": "msg-1",
                "context_hash": context_hash}
        tables = {
            "pedidos": [{"id": pedido_id, "marketplace_integration_id": integration_id,
                         "codigo_pedido_externo": "order-1", "marketplace_order_id": "order-1"}],
            "itens_pedido": [{"id": item_id, "quantidade": 2, "personalizado": True,
                              "pedido_id": pedido_id}],
            "mercadolivre_personalizations": [
                {**base, "id": 1, "quantity_to_personalize": 1, "customization_name": "Ana"},
                {**base, "id": 2, "quantity_to_personalize": 1, "customization_name": "Bia"},
                {**base, "id": 3, "marketplace_integration_id": 8, "updated_at": "2026-10-03T10:00:00+00:00",
                 "quantity_to_personalize": 2, "customization_name": "Outro"},
                {**base, "id": 4, "context_hash": "stale", "updated_at": "2026-10-02T10:00:00+00:00", "quantity_to_personalize": 2,
                 "customization_name": "Antigo"},
            ],
            "mercadolivre_chat_conversations": [{"marketplace_integration_id": integration_id,
                "pack_id": "pack-1", "context_hash": context_hash}],
            "mercadolivre_chat_messages": [{**message, "marketplace_integration_id": integration_id,
                                             "pack_id": "pack-1"}],
        }
        fake_db = FakeDatabase(tables)
        with patch.object(service, "_integration", return_value={}), \
             patch.object(service, "supabase_db", fake_db):
            result = service.printable_personalizations(integration_id, pedido_id)
        self.assertFalse(result["ready"])
        self.assertEqual([row["customization_name"] for row in result["by_item_id"][item_id]], ["Bia", "Antigo"])

    def test_print_is_blocked_by_unconfirmed_review_or_unprocessed_message(self):
        integration_id, pedido_id, item_id = 7, 101, 201
        message = {"provider_message_id": "msg-1", "sender_role": "buyer",
                   "text_content": "Nome Ana", "created_at": "2026-10-01T10:00:00+00:00",
                   "moderation_status": "available", "attachments": []}
        context_hash = service._context_hash([message])
        tables = {
            "pedidos": [{"id": pedido_id, "marketplace_integration_id": integration_id,
                         "codigo_pedido_externo": "order-1"}],
            "itens_pedido": [{"id": item_id, "quantidade": 1, "personalizado": True,
                              "pedido_id": pedido_id}],
            "mercadolivre_chat_conversations": [{"marketplace_integration_id": integration_id,
                "pack_id": "pack-1", "context_hash": context_hash}],
            "mercadolivre_chat_messages": [{**message, "marketplace_integration_id": integration_id,
                                             "pack_id": "pack-1"}],
            "mercadolivre_personalizations": [{
                "marketplace_integration_id": integration_id, "pedido_id": pedido_id,
                "item_pedido_id": item_id, "pack_id": "pack-1", "status": "NEEDS_REVIEW",
                "confirmed": False, "source": "ai", "context_hash": context_hash,
                "quantity_to_personalize": 1, "customization_name": "Ana",
            }],
            "mercadolivre_chat_inbox": [{"id": 1, "marketplace_integration_id": integration_id,
                                         "status": "pending"}],
        }
        with patch.object(service, "_integration", return_value={}), \
             patch.object(service, "supabase_db", FakeDatabase(tables)):
            result = service.printable_personalizations(integration_id, pedido_id)
        self.assertFalse(result["ready"])


class CaptureQuery:
    def __init__(self, tables, name):
        self.tables = tables
        self.name = name
        self.value = None

    def upsert(self, row, **_kwargs):
        self.value = row
        return self

    def execute(self):
        rows = self.value if isinstance(self.value, list) else [self.value]
        self.tables.setdefault(self.name, []).extend(rows)
        return FakeResponse(rows)


if __name__ == "__main__":
    unittest.main()
