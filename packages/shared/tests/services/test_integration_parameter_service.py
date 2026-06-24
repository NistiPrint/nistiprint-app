import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import integration_parameter_service as parameter_module


class TestIntegrationParameterService(unittest.TestCase):
    def test_deep_merge_preserves_defaults(self):
        merged = parameter_module.IntegrationParameterService._deep_merge(
            {"orders": {"warehouse": "A", "series": 1}},
            {"orders": {"series": 2}},
        )
        self.assertEqual(merged, {"orders": {"warehouse": "A", "series": 2}})

    def test_link_mapping_has_precedence_over_installation_and_default(self):
        query = MagicMock()
        query.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"provider_value": "READY", "internal_value": "default", "integration_id": None, "erp_marketplace_link_id": None, "priority": 0},
            {"provider_value": "READY", "internal_value": "install", "integration_id": 12, "erp_marketplace_link_id": None, "priority": 0},
            {"provider_value": "READY", "internal_value": "link", "integration_id": 12, "erp_marketplace_link_id": "abc", "priority": 0},
        ]
        service = parameter_module.IntegrationParameterService()
        with patch.object(parameter_module.supabase_db, "table", return_value=query):
            result = service.resolve_equivalence(
                "shopee", "order_status", "READY",
                integration_id=12, erp_marketplace_link_id="abc",
            )
        self.assertEqual(result, "link")


if __name__ == "__main__":
    unittest.main()

