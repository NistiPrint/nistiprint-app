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
