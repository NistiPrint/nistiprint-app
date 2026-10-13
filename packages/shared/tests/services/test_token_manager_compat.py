import unittest
from unittest.mock import patch

from nistiprint_shared.services.token_manager.token_service import TokenManager


class TokenManagerCompatibilityTests(unittest.TestCase):
    def test_legacy_refresh_delegates_to_the_leased_service(self):
        manager = TokenManager()
        with patch(
            "nistiprint_shared.services.installed_integration_service."
            "installed_integration_service.renew_integration_token"
        ) as renew:
            manager._process_refresh({"id": 7, "module_id": "shopee"})

        renew.assert_called_once_with(
            "7", execution_mode="token_manager_legacy"
        )

    def test_missing_integration_id_does_not_attempt_a_refresh(self):
        manager = TokenManager()
        with patch(
            "nistiprint_shared.services.installed_integration_service."
            "installed_integration_service.renew_integration_token"
        ) as renew:
            manager._process_refresh({"module_id": "bling"})

        renew.assert_not_called()


if __name__ == "__main__":
    unittest.main()
