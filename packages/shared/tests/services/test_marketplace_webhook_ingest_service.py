from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
)


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class MarketplaceWebhookIngestServiceTest(TestCase):
    def _resolve_with_rows(self, module_id, identifier, rows):
        service = MarketplaceWebhookIngestService()
        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db.table",
            return_value=FakeQuery(rows),
        ):
            return service._resolve_marketplace_integration(
                module_id,
                account_identifier=identifier,
                external_order_id="ORDER-1",
            )

    def test_shopee_webhook_shop_id_selects_correct_instance(self):
        rows = [
            {"id": 1, "module_id": "shopee", "config": {"shop_id": "111"}, "credentials": {}},
            {"id": 2, "module_id": "shopee", "config": {"shop_id": "222"}, "credentials": {}},
        ]

        integration, error = self._resolve_with_rows("shopee", "222", rows)

        self.assertIsNone(error)
        self.assertEqual(integration["id"], 2)

    def test_mercadolivre_webhook_user_id_selects_correct_instance(self):
        rows = [
            {"id": 1, "module_id": "mercadolivre", "config": {"user_id": "100"}, "credentials": {}},
            {"id": 2, "module_id": "mercadolivre", "config": {"user_id": "200"}, "credentials": {}},
        ]

        integration, error = self._resolve_with_rows("mercadolivre", "200", rows)

        self.assertIsNone(error)
        self.assertEqual(integration["id"], 2)

    def test_credentials_only_shop_id_still_resolves(self):
        rows = [
            {"id": 1, "module_id": "shopee", "config": {}, "credentials": {"shop_id": "999"}},
            {"id": 2, "module_id": "shopee", "config": {"shop_id": "222"}, "credentials": {}},
        ]

        integration, error = self._resolve_with_rows("shopee", "999", rows)

        self.assertIsNone(error)
        self.assertEqual(integration["id"], 1)

    def test_account_identifier_alias_resolves_instance(self):
        rows = [
            {
                "id": 1,
                "module_id": "mercadolivre",
                "config": {
                    "account_identifiers": {
                        "primary": "100",
                        "kind": "user_id",
                        "aliases": ["seller-100"],
                        "source": "oauth",
                    }
                },
                "credentials": {},
            },
            {"id": 2, "module_id": "mercadolivre", "config": {"user_id": "200"}, "credentials": {}},
        ]

        integration, error = self._resolve_with_rows("mercadolivre", "seller-100", rows)

        self.assertIsNone(error)
        self.assertEqual(integration["id"], 1)

    def test_webhook_without_identifier_and_multiple_instances_is_ambiguous_without_upsert(self):
        rows = [
            {"id": 1, "module_id": "shopee", "config": {"shop_id": "111"}, "credentials": {}},
            {"id": 2, "module_id": "shopee", "config": {"shop_id": "222"}, "credentials": {}},
        ]
        service = MarketplaceWebhookIngestService()
        service._fetch_shopee_detail = MagicMock()

        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db.table",
            return_value=FakeQuery(rows),
        ):
            result = service._process_shopee({"order_sn": "SHP-1"}, correlation_id="corr")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "marketplace_integration_ambiguous")
        service._fetch_shopee_detail.assert_not_called()

    def test_single_instance_without_identity_is_ambiguous_by_default(self):
        rows = [{"id": 1, "module_id": "shopee", "config": {}, "credentials": {}}]

        integration, error = self._resolve_with_rows("shopee", None, rows)

        self.assertIsNone(integration)
        self.assertEqual(error["error_type"], "marketplace_integration_ambiguous")

    def test_default_nfe_link_uses_marketplace_instance_config(self):
        service = MarketplaceWebhookIngestService()
        marketplace = {
            "id": 10,
            "module_id": "shopee",
            "config": {
                "default_nfe_link_id": "link-b",
                "default_nfe_erp_integration_id": 3,
                "default_nfe_shop_id": "AB",
            },
        }
        links = [
            {"id": "link-a", "marketplace_integration_id": 10, "erp_integration_id": 2, "erp_store_id": "AA", "nf_emission_mode": "bling"},
            {"id": "link-b", "marketplace_integration_id": 10, "erp_integration_id": 3, "erp_store_id": "AB", "nf_emission_mode": "bling"},
        ]

        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db.table",
            return_value=FakeQuery(links),
        ):
            link = service._find_default_nfe_link(marketplace)

        self.assertEqual(link["id"], "link-b")
        self.assertEqual(link["erp_integration_id"], 3)
        self.assertEqual(link["erp_store_id"], "AB")

    def test_fetch_shopee_detail_hydrates_integration_before_driver(self):
        service = MarketplaceWebhookIngestService()
        marketplace_inst = {
            "id": 10,
            "module_id": "shopee",
            "config": {"shop_id": "123"},
            "credentials": {"access_token": "token"},
        }
        hydrated = {
            "config": {"shop_id": "123", "partner_id": "456", "partner_key": "secret"},
            "credentials": {"access_token": "token"},
            "access_token": "token",
        }

        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.credential_resolver_service.hydrate_integration",
            return_value=hydrated,
        ) as hydrate, patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.shopee_driver.get_order_detail",
            return_value={"external_id": "SHP-1"},
        ) as get_detail:
            result = service._fetch_shopee_detail(marketplace_inst, "SHP-1")

        hydrate.assert_called_once()
        get_detail.assert_called_once_with(hydrated, ["SHP-1"])
        self.assertEqual(result["external_id"], "SHP-1")

    def test_process_shopee_prefers_bling_materialization_when_linked(self):
        service = MarketplaceWebhookIngestService()
        marketplace_inst = {"id": 7, "module_id": "shopee", "config": {"shop_id": "999"}}
        shopee_detail = {
            "external_id": "SHP-1",
            "order_status": "READY_TO_SHIP",
            "create_time": "2026-06-17T08:00:00-03:00",
            "item_list": [],
        }

        with patch.object(service, "_resolve_marketplace_integration", return_value=(marketplace_inst, None)), \
             patch.object(service, "_find_direct_ingest_link", return_value={"id": "link-1", "channel_id": 55, "ingest_origin_mode": "marketplace_direct"}), \
             patch.object(service, "_find_default_nfe_link", return_value={"erp_integration_id": 22, "erp_store_id": "204047801"}), \
             patch.object(service, "_fetch_shopee_detail", return_value=shopee_detail), \
             patch.object(service, "_upsert_shopee_mirror", return_value=101), \
             patch.object(service, "_try_materialize_from_bling", return_value={
                 "status": "success",
                 "pedido_id": 5001,
                 "pedido_bling_id": 9001,
                 "bling_order_id": 321,
                 "bling_order_number": "B-321",
             }) as materialize, \
             patch.object(service, "_upsert_pedido_status") as upsert_status:
            result = service._process_shopee({"order_sn": "SHP-1", "shop_id": "999"}, correlation_id="corr")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["pedido_id"], 5001)
        self.assertEqual(result["materialized_via"], "bling_lookup")
        materialize.assert_called_once()
        upsert_status.assert_not_called()

    def test_lookup_bling_order_falls_back_to_bling_api_by_numero_loja(self):
        service = MarketplaceWebhookIngestService()

        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        client = MagicMock()
        client.get_order_numbers_by_store_numbers.return_value = [
            {"id": 321, "numero": "B-321", "numeroLoja": "SHP-1"}
        ]

        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.supabase_db.table",
            return_value=table,
        ), patch(
            "nistiprint_shared.services.bling.bling_client.BlingClient.create_client_for_integration_id",
            return_value=client,
        ):
            result = service._lookup_bling_order(bling_integration_id=22, external_order_id="SHP-1")

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["resolved_via"], "bling_api")
        self.assertEqual(result["bling_order_id"], 321)
        self.assertEqual(result["bling_order_number"], "B-321")
