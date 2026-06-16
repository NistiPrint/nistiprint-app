import unittest
from unittest.mock import patch

from nistiprint_shared.services.integration_capability_service import (
    INVOICING,
    ORDER_IMPORT,
    IntegrationCapabilityService,
)


class IntegrationCapabilityServiceTest(unittest.TestCase):
    def test_resolve_invoicing_uses_erp_marketplace_link(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 6,
            "module_id": "mercadolivre",
            "instance_name": "Mercado Livre A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        bling = {
            "id": 2,
            "module_id": "bling",
            "instance_name": "Bling 1",
            "config": {},
            "credentials": {},
            "is_active": True,
            "functional_scopes": ["INVOICING"],
        }
        link = {
            "id": "link-1",
            "marketplace_integration_id": 6,
            "erp_integration_id": 2,
            "ingest_origin_mode": "marketplace_direct",
        }

        with patch.object(service, "_get_installation", side_effect=lambda integration_id: {
            "6": marketplace,
            "2": bling,
            6: marketplace,
            2: bling,
        }.get(integration_id)), patch.object(service, "_get_erp_marketplace_links", return_value=[link]):
            result = service.resolve("6", INVOICING)

        self.assertEqual(result.integration_id, "2")
        self.assertEqual(result.source, "erp_marketplace_links")
        self.assertEqual(result.mode, "single_link")

    def test_resolve_invoicing_uses_order_bling_context_with_multiple_links(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 6,
            "module_id": "shopee",
            "instance_name": "Shopee A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        bling_a = {
            "id": 2,
            "module_id": "bling",
            "instance_name": "Bling A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        bling_b = {
            "id": 3,
            "module_id": "bling",
            "instance_name": "Bling B",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        links = [
            {"id": "aa", "marketplace_integration_id": 6, "erp_integration_id": 2, "erp_store_id": "AA"},
            {"id": "ab", "marketplace_integration_id": 6, "erp_integration_id": 3, "erp_store_id": "AB"},
        ]

        with patch.object(service, "_get_installation", side_effect=lambda integration_id: {
            "6": marketplace,
            "2": bling_a,
            "3": bling_b,
            6: marketplace,
            2: bling_a,
            3: bling_b,
        }.get(integration_id)), patch.object(service, "_get_erp_marketplace_link", return_value=links[1]):
            result = service.resolve("6", INVOICING, context={"bling_integration_id": 3, "erp_store_id": "AB"})

        self.assertEqual(result.integration_id, "3")
        self.assertEqual(result.source, "order_context")
        self.assertEqual(result.mode, "erp")

    def test_resolve_invoicing_uses_shop_id_context_with_multiple_links(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 6,
            "module_id": "shopee",
            "instance_name": "Shopee A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        bling_b = {
            "id": 3,
            "module_id": "bling",
            "instance_name": "Bling B",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        link = {"id": "ab", "marketplace_integration_id": 6, "erp_integration_id": 3, "erp_store_id": "AB"}

        with patch.object(service, "_get_installation", side_effect=lambda integration_id: {
            "6": marketplace,
            "3": bling_b,
            6: marketplace,
            3: bling_b,
        }.get(integration_id)), patch.object(service, "_get_erp_marketplace_link", return_value=link):
            result = service.resolve("6", INVOICING, context={"shop_id": "AB"})

        self.assertEqual(result.integration_id, "3")
        self.assertEqual(result.source, "erp_marketplace_links")
        self.assertEqual(result.mode, "erp_store")

    def test_resolve_invoicing_blocks_ambiguous_marketplace_links(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 6,
            "module_id": "shopee",
            "instance_name": "Shopee A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        links = [
            {"id": "aa", "marketplace_integration_id": 6, "erp_integration_id": 2, "erp_store_id": "AA"},
            {"id": "ab", "marketplace_integration_id": 6, "erp_integration_id": 3, "erp_store_id": "AB"},
        ]

        with patch.object(service, "_get_installation", return_value=marketplace), patch.object(service, "_get_erp_marketplace_links", return_value=links):
            result = service.resolve("6", INVOICING)

        self.assertIsNone(result.responsible_integration)
        self.assertEqual(result.reason, "ambiguous_erp_link")

    def test_resolve_invoicing_uses_marketplace_default_nfe_route(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 6,
            "module_id": "shopee",
            "instance_name": "Shopee A",
            "config": {
                "default_nfe_erp_integration_id": 3,
                "default_nfe_shop_id": "AB",
                "default_nfe_link_id": "ab",
            },
            "credentials": {},
            "is_active": True,
        }
        bling_b = {
            "id": 3,
            "module_id": "bling",
            "instance_name": "Bling B",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        link = {"id": "ab", "marketplace_integration_id": 6, "erp_integration_id": 3, "erp_store_id": "AB"}

        with patch.object(service, "_get_installation", side_effect=lambda integration_id: {
            "6": marketplace,
            "3": bling_b,
            6: marketplace,
            3: bling_b,
        }.get(integration_id)), patch.object(service, "_get_erp_marketplace_link", return_value=link):
            result = service.resolve("6", INVOICING)

        self.assertEqual(result.integration_id, "3")
        self.assertEqual(result.source, "marketplace_default_nfe")
        self.assertEqual(result.link["id"], "ab")

    def test_resolve_order_import_prefers_direct_shopee(self):
        service = IntegrationCapabilityService()
        marketplace = {
            "id": 7,
            "module_id": "shopee",
            "instance_name": "Shopee A",
            "config": {},
            "credentials": {},
            "is_active": True,
        }
        link = {
            "id": "link-2",
            "marketplace_integration_id": 7,
            "bling_integration_id": 3,
            "ingest_origin_mode": "marketplace_direct",
        }

        with patch.object(service, "_get_installation", return_value=marketplace), patch.object(service, "_get_channel_connection", return_value=link):
            result = service.resolve("7", ORDER_IMPORT)

        self.assertEqual(result.integration_id, "7")
        self.assertEqual(result.mode, "marketplace_direct")
        self.assertEqual(result.source, "ingest_origin_mode")


if __name__ == "__main__":
    unittest.main()
