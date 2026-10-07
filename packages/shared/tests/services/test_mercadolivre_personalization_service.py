import unittest
from unittest.mock import patch

from nistiprint_shared.services import mercadolivre_personalization_service as service
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
                {**base, "id": 3, "marketplace_integration_id": 8,
                 "quantity_to_personalize": 2, "customization_name": "Outro"},
                {**base, "id": 4, "context_hash": "stale", "quantity_to_personalize": 2,
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
        self.assertTrue(result["ready"])
        self.assertEqual([row["customization_name"] for row in result["by_item_id"][item_id]], ["Ana", "Bia"])

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
