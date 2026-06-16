import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.installed_integration_service import InstalledIntegrationService


class InstalledIntegrationServiceTest(unittest.TestCase):
    def test_update_refresh_error_does_not_clear_config_or_credentials(self):
        service = InstalledIntegrationService()
        service.table = MagicMock()
        update_query = service.table.update.return_value
        update_query.eq.return_value.execute.return_value.data = [{"id": 6}]

        with patch.object(service, "get_installed_by_id") as get_installed:
            result = service.update_installed("6", {"refresh_error": "erro"})

        self.assertTrue(result)
        get_installed.assert_not_called()
        update_payload = service.table.update.call_args.args[0]
        self.assertEqual(update_payload["refresh_error"], "erro")
        self.assertNotIn("config", update_payload)
        self.assertNotIn("credentials", update_payload)

    def test_update_token_fields_preserves_normalized_config_and_credentials(self):
        service = InstalledIntegrationService()
        service.table = MagicMock()
        update_query = service.table.update.return_value
        update_query.eq.return_value.execute.return_value.data = [{"id": 6}]

        current = MagicMock()
        current.id = "6"
        current.to_dict.return_value = {
            "module_id": "shopee",
            "config": {"shop_id": "456"},
            "credentials": {"access_token": "old-token"},
        }

        with patch.object(service, "get_installed_by_id", return_value=current):
            result = service.update_installed("6", {"access_token": "new-token"})

        self.assertTrue(result)
        update_payload = service.table.update.call_args.args[0]
        self.assertEqual(update_payload["access_token"], "new-token")
        self.assertEqual(update_payload["config"]["shop_id"], "456")
        self.assertEqual(update_payload["credentials"]["access_token"], "new-token")


if __name__ == "__main__":
    unittest.main()
