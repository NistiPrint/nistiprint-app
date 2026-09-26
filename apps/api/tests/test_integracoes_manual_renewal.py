import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.integracoes as integracoes_module  # noqa: E402


class TestManualIntegrationRenewal(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True)
        app.register_blueprint(integracoes_module.integracoes_api_bp)
        self.client = app.test_client()

    @patch.object(
        integracoes_module.installed_integration_service,
        "renew_integration_token",
    )
    @patch.object(
        integracoes_module.installed_integration_service,
        "get_installed_by_id",
        return_value=SimpleNamespace(module_id="bling"),
    )
    def test_manual_renewal_uses_unified_vault_flow(self, get_integration, renew):
        response = self.client.post("/api/v2/integracoes/renovar/17")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")
        get_integration.assert_called_once_with("17")
        renew.assert_called_once_with("17", execution_mode="manual")

    @patch.object(
        integracoes_module.installed_integration_service,
        "update_installed",
        return_value=True,
    )
    @patch.object(
        integracoes_module.installed_integration_service,
        "renew_integration_token",
        side_effect=ValueError("access_token JWT invalido"),
    )
    @patch.object(
        integracoes_module.installed_integration_service,
        "get_installed_by_id",
        return_value=SimpleNamespace(module_id="bling"),
    )
    def test_failed_manual_renewal_reports_error_without_direct_token_write(
        self, get_integration, renew, update
    ):
        response = self.client.post("/api/v2/integracoes/renovar/17")

        self.assertEqual(response.status_code, 400)
        self.assertIn("JWT", response.get_json()["message"])
        get_integration.assert_called_once_with("17")
        renew.assert_called_once_with("17", execution_mode="manual")
        self.assertEqual(update.call_args.args[0], "17")
        self.assertIn("refresh_error", update.call_args.args[1])
        self.assertNotIn("access_token", update.call_args.args[1])
        self.assertNotIn("refresh_token", update.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
