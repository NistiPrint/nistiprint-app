from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.token_renewal_service import TokenRenewalService


class TokenRenewalServiceTest(TestCase):
    def _client_with_integrations(self, integrations):
        table = MagicMock()
        table.select.return_value.eq.return_value.execute.return_value.data = integrations
        client = MagicMock()
        client.table.return_value = table
        return client

    def _token_side_effect(self, token_matrix):
        def side_effect(installation, secret_kind):
            return token_matrix.get((installation.get("id"), secret_kind), False)

        return side_effect

    def test_renews_expiring_and_degraded_app_managed_integrations(self):
        now = datetime.now(timezone.utc)
        integrations = [
            {
                "id": 6,
                "module_id": "shopee",
                "instance_name": "Shopee",
                "expires_at": (now + timedelta(hours=2)).isoformat(),
                "refresh_error": None,
            },
            {
                "id": 7091,
                "module_id": "mercadolivre",
                "instance_name": "Mercado Livre",
                "expires_at": (now + timedelta(hours=8)).isoformat(),
                "refresh_error": "token falhou",
                "last_refresh_attempt": (now - timedelta(hours=7)).isoformat(),
            },
        ]
        token_matrix = {
            (6, "access_token"): True,
            (6, "refresh_token"): True,
            (7091, "access_token"): True,
            (7091, "refresh_token"): True,
        }
        service = TokenRenewalService()

        with patch(
            "nistiprint_shared.services.token_renewal_service.supabase_db.client",
            self._client_with_integrations(integrations),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.credential_resolver_service.has_installation_token",
            side_effect=self._token_side_effect(token_matrix),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.installed_integration_service.renew_integration_token"
        ) as renew_token:
            result = service.renew_app_managed_credentials()

        self.assertEqual(renew_token.call_count, 2)
        renew_token.assert_any_call("6", execution_mode="scheduled")
        renew_token.assert_any_call("7091", execution_mode="scheduled")
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["renewed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["by_module"]["shopee"]["renewed"], 1)
        self.assertEqual(result["by_module"]["mercadolivre"]["renewed"], 1)

    def test_skips_unsupported_missing_refresh_and_not_expiring_integrations(self):
        now = datetime.now(timezone.utc)
        integrations = [
            {
                "id": 1,
                "module_id": "bling",
                "instance_name": "Bling",
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
            {
                "id": 6,
                "module_id": "shopee",
                "instance_name": "Shopee sem refresh",
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
            {
                "id": 7091,
                "module_id": "mercadolivre",
                "instance_name": "ML ainda valido",
                "expires_at": (now + timedelta(hours=12)).isoformat(),
                "refresh_error": None,
            },
        ]
        token_matrix = {
            (1, "access_token"): True,
            (1, "refresh_token"): True,
            (6, "access_token"): True,
            (6, "refresh_token"): False,
            (7091, "access_token"): True,
            (7091, "refresh_token"): True,
        }
        service = TokenRenewalService()

        with patch(
            "nistiprint_shared.services.token_renewal_service.supabase_db.client",
            self._client_with_integrations(integrations),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.credential_resolver_service.has_installation_token",
            side_effect=self._token_side_effect(token_matrix),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.installed_integration_service.renew_integration_token"
        ) as renew_token:
            result = service.renew_app_managed_credentials()

        renew_token.assert_not_called()
        self.assertEqual(result["processed"], 3)
        self.assertEqual(result["renewed"], 0)
        self.assertEqual(result["skipped"], 3)
        self.assertEqual(result["skip_reasons"]["unsupported_strategy"], 1)
        self.assertEqual(result["skip_reasons"]["missing_refresh_token"], 1)
        self.assertEqual(result["skip_reasons"]["not_expiring"], 1)

    def test_respects_retry_cooldown_for_degraded_credentials(self):
        now = datetime.now(timezone.utc)
        integrations = [
            {
                "id": 7091,
                "module_id": "mercadolivre",
                "instance_name": "Mercado Livre",
                "expires_at": (now + timedelta(hours=8)).isoformat(),
                "refresh_error": "token falhou",
                "last_refresh_attempt": (now - timedelta(hours=2)).isoformat(),
            }
        ]
        token_matrix = {
            (7091, "access_token"): True,
            (7091, "refresh_token"): True,
        }
        service = TokenRenewalService()

        with patch(
            "nistiprint_shared.services.token_renewal_service.supabase_db.client",
            self._client_with_integrations(integrations),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.credential_resolver_service.has_installation_token",
            side_effect=self._token_side_effect(token_matrix),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.installed_integration_service.renew_integration_token"
        ) as renew_token:
            result = service.renew_app_managed_credentials()

        renew_token.assert_not_called()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["skip_reasons"]["cooldown_active"], 1)

    def test_renews_when_refresh_token_exists_but_access_token_is_missing(self):
        integrations = [
            {
                "id": 6,
                "module_id": "shopee",
                "instance_name": "Shopee",
                "expires_at": None,
                "refresh_error": None,
            }
        ]
        token_matrix = {
            (6, "access_token"): False,
            (6, "refresh_token"): True,
        }
        service = TokenRenewalService()

        with patch(
            "nistiprint_shared.services.token_renewal_service.supabase_db.client",
            self._client_with_integrations(integrations),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.credential_resolver_service.has_installation_token",
            side_effect=self._token_side_effect(token_matrix),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.installed_integration_service.renew_integration_token"
        ) as renew_token:
            result = service.renew_app_managed_credentials()

        renew_token.assert_called_once_with("6", execution_mode="scheduled")
        self.assertEqual(result["renewed"], 1)

    def test_records_failure_and_counts_failed_integrations(self):
        now = datetime.now(timezone.utc)
        integrations = [
            {
                "id": 6,
                "module_id": "shopee",
                "instance_name": "Shopee",
                "expires_at": (now + timedelta(hours=2)).isoformat(),
                "refresh_error": None,
            }
        ]
        token_matrix = {
            (6, "access_token"): True,
            (6, "refresh_token"): True,
        }
        service = TokenRenewalService()

        with patch(
            "nistiprint_shared.services.token_renewal_service.supabase_db.client",
            self._client_with_integrations(integrations),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.credential_resolver_service.has_installation_token",
            side_effect=self._token_side_effect(token_matrix),
        ), patch(
            "nistiprint_shared.services.token_renewal_service.installed_integration_service.renew_integration_token",
            side_effect=Exception("boom"),
        ), patch.object(service, "_record_failure") as record_failure:
            result = service.renew_app_managed_credentials()

        record_failure.assert_called_once()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["renewed"], 0)
        self.assertEqual(result["by_module"]["shopee"]["failed"], 1)

    def test_legacy_provider_methods_delegate_to_unified_service(self):
        service = TokenRenewalService()

        with patch.object(service, "renew_app_managed_credentials", return_value={"status": "SUCCESS"}) as renew:
            service.renew_shopee_tokens_expiring_soon()
            service.renew_mercadolivre_tokens_expiring_soon()

        self.assertEqual(renew.call_count, 2)
        renew.assert_any_call(
            expiry_threshold=timedelta(hours=3),
            module_filter="shopee",
        )
        renew.assert_any_call(
            expiry_threshold=timedelta(hours=3),
            module_filter="mercadolivre",
        )
