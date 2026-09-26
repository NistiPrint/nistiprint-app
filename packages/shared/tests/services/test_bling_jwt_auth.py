import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.bling.bling_client import (
    BlingClient as PrimaryBlingClient,
)
from nistiprint_shared.services.bling.bling_client_updated import (
    BlingClient as SecondaryBlingClient,
)


class BlingJWTAuthTest(unittest.TestCase):
    @staticmethod
    def _success_response():
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {}}
        return response

    def _make_account(self, token):
        return {
            "id": None,
            "access_token": token,
            "refresh_token": "refresh",
            "expires_in": 3600,
            "client_id": "client",
            "client_secret": "secret",
            "created_at": "2026-06-26T10:00:00+00:00",
            "updated_at": "2026-06-26T10:00:00+00:00",
        }

    def test_both_clients_send_jwt_header_with_long_access_tokens(self):
        token = f"{'a' * 998}.{'b' * 999}.{'c' * 999}"

        with patch(
            "nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.acquire",
            return_value={"granted": True},
        ), patch(
            "nistiprint_shared.services.bling.bling_client.requests.request",
            return_value=self._success_response(),
        ) as primary_request:
            PrimaryBlingClient(self._make_account(token))._request("GET", "produtos")

        with patch(
            "nistiprint_shared.services.bling.bling_client_updated.requests.request",
            return_value=self._success_response(),
        ) as secondary_request:
            SecondaryBlingClient(self._make_account(token))._request("GET", "produtos")

        self.assertGreater(len(token), 2900)
        for request_mock in (primary_request, secondary_request):
            headers = request_mock.call_args.kwargs["headers"]
            self.assertEqual(headers["Authorization"], f"Bearer {token}")
            self.assertEqual(headers["enable-jwt"], "1")

    def test_both_clients_send_jwt_header_when_checking_token(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"

        with patch(
            "nistiprint_shared.services.bling.bling_client.requests.get",
            return_value=self._success_response(),
        ) as primary_get:
            self.assertTrue(
                PrimaryBlingClient(self._make_account(token)).check_token_simple()
            )

        with patch(
            "nistiprint_shared.services.bling.bling_client_updated.requests.get",
            return_value=self._success_response(),
        ) as secondary_get:
            self.assertTrue(
                SecondaryBlingClient(self._make_account(token)).check_token_simple()
            )

        for get_mock in (primary_get, secondary_get):
            headers = get_mock.call_args.kwargs["headers"]
            self.assertEqual(headers["Authorization"], f"Bearer {token}")
            self.assertEqual(headers["enable-jwt"], "1")

    def test_refresh_rejects_opaque_token_without_replacing_current_token(self):
        for client_class, module_path in (
            (PrimaryBlingClient, "bling_client"),
            (SecondaryBlingClient, "bling_client_updated"),
        ):
            with self.subTest(client=module_path):
                client = client_class(self._make_account("old-token"))
                response = MagicMock()
                response.json.return_value = {
                    "access_token": "opaque-token",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                }

                with patch(
                    f"nistiprint_shared.services.bling.{module_path}.requests.post",
                    return_value=response,
                ) as post_mock:
                    with redirect_stdout(StringIO()):
                        with self.assertRaisesRegex(ValueError, "access_token JWT"):
                            client._refresh_token()

                self.assertEqual(client.access_token, "old-token")
                self.assertEqual(client.refresh_token, "refresh")
                self.assertEqual(post_mock.call_args.kwargs["headers"]["enable-jwt"], "1")


if __name__ == "__main__":
    unittest.main()
