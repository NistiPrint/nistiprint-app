from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch

from nistiprint_shared.services.integration_credentials_service import (
    integration_credentials_service,
)


class IntegrationCredentialsServiceTest(TestCase):
    def test_batch_secret_presence_preserves_public_token_status_without_per_token_queries(self):
        installation = {
            "id": 1,
            "module_id": "bling",
            "config": {},
            "credentials": {},
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat(),
        }

        with patch(
            "nistiprint_shared.services.integration_credentials_service.credential_resolver_service.has_installation_token"
        ) as has_token:
            public = integration_credentials_service.public_view(
                installation,
                installation_secret_kinds={"access_token", "refresh_token"},
            )

        self.assertEqual(public["token_status"], "valid")
        self.assertTrue(public["actions"]["can_test_connection"])
        self.assertEqual(has_token.call_count, 2)
        self.assertTrue(all(call.kwargs["secret_is_present"] for call in has_token.call_args_list))

    def test_sanitization_uses_batch_presence_without_returning_secret_values(self):
        installation = {
            "id": 21,
            "module_id": "mercadolivre",
            "config": {},
            "credentials": {"access_token": "private-access", "refresh_token": "private-refresh"},
            "access_token": "private-access",
            "refresh_token": "private-refresh",
        }

        public = integration_credentials_service.sanitize_installation(
            installation,
            installation_secret_kinds={"access_token", "refresh_token"},
        )

        self.assertEqual(public["credential_status"]["token_status"], "valid")
        self.assertTrue(public["credential_status"]["has_access_token"])
        self.assertTrue(public["credential_status"]["has_refresh_token"])
        self.assertNotIn("access_token", public)
        self.assertNotIn("refresh_token", public)
        self.assertNotIn("access_token", public["credentials"])
        self.assertNotIn("refresh_token", public["credentials"])

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
