from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from nistiprint_shared.services.integration_credentials_service import (
    integration_credentials_service,
)


class IntegrationCredentialsServiceTest(TestCase):
    def test_bling_is_app_managed_and_can_refresh(self):
        installation = {
            "id": 1,
            "module_id": "bling",
            "config": {"cnpj": "12345678000199"},
            "credentials": {},
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        with patch(
            "nistiprint_shared.services.integration_credentials_service.credential_resolver_service.has_installation_token",
            side_effect=[True, True],
        ):
            public = integration_credentials_service.public_view(installation)

        self.assertEqual(public["management_mode"], "app_managed")
        self.assertEqual(public["source_system"], "supabase")
        self.assertTrue(public["actions"]["can_refresh"])
        self.assertFalse(public["actions"]["can_sync_external"])

    def test_expired_marketplace_token_is_reported(self):
        installation = {
            "id": 6,
            "module_id": "shopee",
            "config": {"shop_id": "111"},
            "credentials": {"shop_id": "111"},
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        with patch(
            "nistiprint_shared.services.integration_credentials_service.credential_resolver_service.has_installation_token",
            side_effect=[True, True],
        ):
            public = integration_credentials_service.public_view(installation)

        self.assertEqual(public["token_status"], "expired")
        self.assertTrue(public["actions"]["can_refresh"])
        self.assertEqual(public["account_identifier"], "111")

    def test_missing_token_for_non_oauth_module_is_not_required(self):
        installation = {
            "id": 7092,
            "module_id": "shein",
            "config": {},
            "credentials": {},
        }

        with patch(
            "nistiprint_shared.services.integration_credentials_service.credential_resolver_service.has_installation_token",
            side_effect=[False, False],
        ):
            public = integration_credentials_service.public_view(installation)

        self.assertEqual(public["token_status"], "not_required")
        self.assertEqual(public["connection_status"], "not_applicable")
