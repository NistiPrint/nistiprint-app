import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.erp_links as erp_links_routes  # noqa: E402


class ErpLinksBatchRouteTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        app.register_blueprint(erp_links_routes.erp_links_bp)
        self.client = app.test_client()

    @patch.object(
        erp_links_routes.erp_marketplace_links_service,
        "get_links_for_integrations",
        return_value={"erp": {"1": []}, "marketplace": {"8": []}},
    )
    def test_returns_grouped_links_for_both_integration_types(self, get_links):
        response = self.client.get(
            "/api/v2/erp-links/batch?erp_ids=1&marketplace_ids=8"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["erp"], {"1": []})
        self.assertEqual(response.get_json()["data"]["marketplace"], {"8": []})
        get_links.assert_called_once_with([1], [8])

    def test_rejects_invalid_ids_without_querying_service(self):
        with patch.object(
            erp_links_routes.erp_marketplace_links_service,
            "get_links_for_integrations",
        ) as get_links:
            response = self.client.get("/api/v2/erp-links/batch?erp_ids=invalid")

        self.assertEqual(response.status_code, 400)
        get_links.assert_not_called()


if __name__ == "__main__":
    unittest.main()
