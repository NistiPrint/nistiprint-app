import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.credential_resolver_service import CredentialContext
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

    def test_update_token_fields_do_not_repopulate_public_credentials(self):
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
        self.assertNotIn("config", update_payload)
        self.assertNotIn("credentials", update_payload)

    def test_renew_token_uses_resolved_credential_context(self):
        service = InstalledIntegrationService()
        service.table = MagicMock()
        service.log_table = MagicMock()

        current = MagicMock()
        current.id = "9"
        current.module_id = "shopee"
        current.to_dict.return_value = {
            "module_id": "shopee",
            "config": {"shop_id": "456"},
            "credentials": {"refresh_token": "legacy-refresh"},
        }

        context = CredentialContext(
            module_id="shopee",
            installation={"id": "9", "module_id": "shopee"},
            app_profile={"id": "11"},
            app_secrets={"partner_id": "123", "partner_key": "secret"},
            installation_secrets={"refresh_token": "refresh-123"},
            config={"shop_id": "456"},
            credentials={"shop_id": "456"},
        )

        with patch.object(service, "get_installed_by_id", return_value=current), \
             patch("nistiprint_shared.services.installed_integration_service.integration_credentials_service.ensure_refresh_allowed"), \
             patch("nistiprint_shared.services.installed_integration_service.credential_resolver_service.resolve_for_installation", return_value=context) as resolve_context, \
             patch("nistiprint_shared.services.installed_integration_service.platform_auth_service.refresh_access_token", return_value={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}) as refresh_access_token, \
             patch("nistiprint_shared.services.installed_integration_service.credential_resolver_service.persist_installation_tokens") as persist_tokens, \
             patch.object(service, "update_installed", return_value=True) as update_installed, \
             patch("nistiprint_shared.services.installed_integration_service.bling_firebase_projection_service.publish_installation_by_id") as publish_firebase, \
             patch("nistiprint_shared.services.installed_integration_service.file_archive_service.append"):
            result = service.renew_integration_token("9")

        resolve_context.assert_called_once()
        refresh_access_token.assert_called_once_with("shopee", context)
        persist_tokens.assert_called_once()
        update_payload = update_installed.call_args.args[1]
        self.assertTrue(update_payload["last_refresh_attempt"].endswith("+00:00"))
        self.assertTrue(update_payload["expires_at"].endswith("+00:00"))
        publish_firebase.assert_not_called()
        self.assertEqual(result["access_token"], "new-access")
        self.assertEqual(result["refresh_token"], "new-refresh")

    def test_renew_bling_token_publishes_to_firebase(self):
        service = InstalledIntegrationService()
        service.table = MagicMock()
        service.log_table = MagicMock()

        current = MagicMock()
        current.id = "11"
        current.module_id = "bling"
        current.to_dict.return_value = {
            "module_id": "bling",
            "config": {"cnpj": "12345678000199"},
            "credentials": {"refresh_token": "legacy-refresh"},
        }

        context = CredentialContext(
            module_id="bling",
            installation={"id": "11", "module_id": "bling"},
            app_profile={"id": "22"},
            app_secrets={"client_id": "client", "client_secret": "secret"},
            installation_secrets={"refresh_token": "refresh-123"},
            config={"cnpj": "12345678000199"},
            credentials={},
        )

        with patch.object(service, "get_installed_by_id", return_value=current), \
             patch("nistiprint_shared.services.installed_integration_service.integration_credentials_service.ensure_refresh_allowed"), \
             patch("nistiprint_shared.services.installed_integration_service.credential_resolver_service.resolve_for_installation", return_value=context), \
             patch("nistiprint_shared.services.installed_integration_service.platform_auth_service.refresh_access_token", return_value={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}), \
             patch("nistiprint_shared.services.installed_integration_service.credential_resolver_service.persist_installation_tokens"), \
             patch.object(service, "update_installed", return_value=True), \
             patch("nistiprint_shared.services.installed_integration_service.bling_firebase_projection_service.publish_installation_by_id", return_value={"doc_id": "12345678000199"}) as publish_firebase, \
             patch("nistiprint_shared.services.installed_integration_service.file_archive_service.append"):
            result = service.renew_integration_token("11")

        publish_firebase.assert_called_once_with("11")
        self.assertEqual(result["firebase_projection"], {"doc_id": "12345678000199"})


if __name__ == "__main__":
    unittest.main()
