import unittest
from unittest.mock import patch

from nistiprint_shared.services.credential_resolver_service import CredentialContext
from nistiprint_shared.services.platform_auth_service import platform_auth_service
from nistiprint_shared.services.platform_drivers import mercadolivre
from nistiprint_shared.services.platform_drivers import shopee


class PlatformAuthServiceTest(unittest.TestCase):
    @patch("nistiprint_shared.services.platform_auth_service.requests.get")
    def test_shopee_test_accepts_legacy_top_level_credentials(self, mock_get):
        mock_get.return_value.json.return_value = {"success": True}

        result = platform_auth_service._test_shopee(
            {
                "partner_id": "123",
                "partner_key": "secret",
                "shop_id": "456",
            },
            "/api/v2/shop/get_shop_info",
            "token",
        )

        self.assertEqual(result, {"success": True})
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["partner_id"], 123)
        self.assertEqual(params["shop_id"], 456)

    @patch("nistiprint_shared.services.platform_auth_service.requests.get")
    def test_shopee_test_accepts_account_identifier_shop_id(self, mock_get):
        mock_get.return_value.json.return_value = {"success": True}

        result = platform_auth_service._test_shopee(
            {
                "config": {
                    "partner_id": "123",
                    "partner_key": "secret",
                    "account_identifiers": {
                        "kind": "shop_id",
                        "primary": "456",
                    },
                },
            },
            "/api/v2/shop/get_shop_info",
            "token",
        )

        self.assertEqual(result, {"success": True})
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["shop_id"], 456)

    @patch.dict("os.environ", {"SHOPEE_PARTNER_ID": "123", "SHOPEE_PARTNER_KEY": "secret"})
    @patch("nistiprint_shared.services.platform_drivers.shopee.requests.get")
    def test_shopee_driver_test_uses_environment_partner_credentials(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"response": {"shop_name": "Loja"}}

        result = shopee.test_connection(
            {
                "config": {"shop_id": "456"},
                "credentials": {"access_token": "token"},
            }
        )

        self.assertTrue(result["success"])
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["partner_id"], 123)
        self.assertEqual(params["shop_id"], 456)

    @patch("nistiprint_shared.services.platform_drivers.mercadolivre.requests.get")
    def test_mercadolivre_driver_test_uses_credentials_token(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": 100}

        result = mercadolivre.test_connection(
            {
                "credentials": {"access_token": "token"},
            }
        )

        self.assertTrue(result["success"])
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer token")

    @patch("nistiprint_shared.services.platform_drivers.mercadolivre.requests.get")
    def test_mercadolivre_driver_test_uses_top_level_token(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": 200}

        result = mercadolivre.test_connection(
            {
                "access_token": "top-token",
                "credentials": {},
            }
        )

        self.assertTrue(result["success"])
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer top-token")

    def test_generate_auth_url_uses_app_profile_credentials_and_pkce(self):
        context = CredentialContext(
            module_id="mercadolivre",
            installation={"id": "inst-1", "module_id": "mercadolivre"},
            app_profile={"id": "profile-1", "redirect_uri": "https://app.example.com/callback"},
            app_secrets={"client_id": "client-123"},
            installation_secrets={},
            config={},
            credentials={},
        )

        auth_url = platform_auth_service.generate_auth_url(
            "mercadolivre",
            context,
            "https://app.example.com/callback",
            state="opaque-state",
            code_challenge="challenge-123",
        )

        self.assertIn("client_id=client-123", auth_url)
        self.assertIn("state=opaque-state", auth_url)
        self.assertIn("code_challenge_method=S256", auth_url)
        self.assertIn("code_challenge=challenge-123", auth_url)

    @patch("nistiprint_shared.services.platform_auth_service.requests.get")
    def test_resolve_account_identity_fetches_mercadolivre_user_when_missing_in_token(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": 987654}

        identity = platform_auth_service.resolve_account_identity(
            "mercadolivre",
            {"access_token": "token", "raw_response": {}},
        )

        self.assertEqual(identity, "987654")
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer token")

    @patch("nistiprint_shared.services.platform_auth_service.requests.get")
    def test_resolve_installation_account_identity_fetches_mercadolivre_user_from_context(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"id": 112233}

        context = CredentialContext(
            module_id="mercadolivre",
            installation={"id": "inst-1", "module_id": "mercadolivre"},
            app_profile={"id": "profile-1"},
            app_secrets={},
            installation_secrets={"access_token": "secret-token"},
            config={},
            credentials={},
        )

        identity = platform_auth_service.resolve_installation_account_identity(
            "mercadolivre",
            context,
        )

        self.assertEqual(identity, "112233")
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer secret-token")

    def test_resolve_installation_account_identity_uses_existing_shop_id(self):
        context = CredentialContext(
            module_id="shopee",
            installation={"id": "inst-2", "module_id": "shopee"},
            app_profile={"id": "profile-2"},
            app_secrets={},
            installation_secrets={},
            config={
                "account_identifiers": {
                    "kind": "shop_id",
                    "primary": "445566",
                }
            },
            credentials={},
        )

        identity = platform_auth_service.resolve_installation_account_identity(
            "shopee",
            context,
        )

        self.assertEqual(identity, "445566")


if __name__ == "__main__":
    unittest.main()
