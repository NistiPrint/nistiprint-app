import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.erp_marketplace_links_service import (
    ErpMarketplaceLinksService,
)


class ErpMarketplaceLinksServiceTest(unittest.TestCase):
    @patch("nistiprint_shared.services.erp_marketplace_links_service.supabase_db")
    def test_loads_both_directions_in_two_queries_and_groups_empty_integrations(self, db):
        service = ErpMarketplaceLinksService()
        query = MagicMock()
        query.select.return_value = query
        query.in_.return_value = query
        query.execute.side_effect = [
            SimpleNamespace(
                data=[
                    {
                        "id": 101,
                        "erp_integration_id": 1,
                        "marketplace_integration_id": 8,
                        "marketplace_module_id": "shopee",
                        "marketplace": None,
                    }
                ]
            ),
            SimpleNamespace(
                data=[
                    {
                        "id": 101,
                        "erp_integration_id": 1,
                        "marketplace_integration_id": 8,
                        "erp": {"id": 1, "instance_name": "Bling"},
                    }
                ]
            ),
        ]
        db.table.return_value = query

        result = service.get_links_for_integrations([1, 2, 1], [8, 9])

        self.assertEqual(len(result["erp"]["1"]), 1)
        self.assertEqual(result["erp"]["1"][0]["id"], "101")
        self.assertTrue(result["erp"]["1"][0]["marketplace"]["catalog_only"])
        self.assertEqual(result["erp"]["2"], [])
        self.assertEqual(len(result["marketplace"]["8"]), 1)
        self.assertEqual(result["marketplace"]["9"], [])
        self.assertEqual(query.execute.call_count, 2)

    @patch("nistiprint_shared.services.erp_marketplace_links_service.supabase_db")
    def test_empty_id_lists_do_not_query_database(self, db):
        result = ErpMarketplaceLinksService().get_links_for_integrations([], [])

        self.assertEqual(result, {"erp": {}, "marketplace": {}})
        db.table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
