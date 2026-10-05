import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.marketplace_api_routes as marketplace_routes  # noqa: E402


class InstalledIntegrationsBatchSecretsTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        app.register_blueprint(marketplace_routes.marketplace_api_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1

    @patch.object(
        marketplace_routes.integration_secret_service,
        "secret_kinds_for_owners",
        return_value={"5": {"access_token", "refresh_token"}},
    )
    @patch.object(
        marketplace_routes.installed_integration_service,
        "get_all_installed",
        return_value=[
            SimpleNamespace(
                id=5,
                module_id="mercadolivre",
                to_dict=lambda: {
                    "id": 5,
                    "module_id": "mercadolivre",
                    "credentials": {
                        "access_token": "private-access",
                        "refresh_token": "private-refresh",
                    },
                    "access_token": "private-access",
                    "refresh_token": "private-refresh",
                },
            )
        ],
    )
    def test_list_reads_secret_presence_once_and_still_sanitizes_values(self, get_installations, get_secret_kinds):
        response = self.client.get("/api/v2/marketplace/installed")

        self.assertEqual(response.status_code, 200)
        get_secret_kinds.assert_called_once_with(
            "installed_integration", [5], ["access_token", "refresh_token"]
        )
        installation = response.get_json()["installations"][0]
        self.assertTrue(installation["credential_status"]["has_access_token"])
        self.assertTrue(installation["credential_status"]["has_refresh_token"])
        self.assertNotIn("access_token", installation)
        self.assertNotIn("refresh_token", installation)
        self.assertNotIn("access_token", installation["credentials"])
        self.assertNotIn("refresh_token", installation["credentials"])


if __name__ == "__main__":
    unittest.main()
