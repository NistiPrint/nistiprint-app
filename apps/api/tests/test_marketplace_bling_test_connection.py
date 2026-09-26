import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.marketplace_api_routes as marketplace_routes  # noqa: E402


class TestMarketplaceBlingConnection(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        app.register_blueprint(marketplace_routes.marketplace_api_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    @patch.object(marketplace_routes.platform_api_service, "test_connection")
    @patch.object(
        marketplace_routes.platform_auth_service,
        "call_test_endpoint",
        return_value={"success": False, "error": "FORBIDDEN"},
    )
    @patch.object(marketplace_routes, "_auth_payload_for_test", return_value={"access_token": "jwt"})
    @patch.object(
        marketplace_routes.installed_integration_service,
        "get_installed_by_id",
        return_value=SimpleNamespace(module_id="bling"),
    )
    def test_bling_connection_uses_bling_auth_test_and_reports_failure(
        self, _get_integration, _payload, call_test, generic_test
    ):
        response = self.client.post("/api/v2/marketplace/installed/1/test")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["success"])
        self.assertEqual(response.get_json()["result"]["error"], "FORBIDDEN")
        call_test.assert_called_once_with("bling", {"access_token": "jwt"})
        generic_test.assert_not_called()


if __name__ == "__main__":
    unittest.main()
