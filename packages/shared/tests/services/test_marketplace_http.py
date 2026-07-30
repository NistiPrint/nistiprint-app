import unittest
from unittest.mock import Mock

import requests

from nistiprint_shared.services.marketplace_http import request_json


class FakeResponse:
    def __init__(self, status, payload=None, *, text="", headers=None, json_error=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class TestMarketplaceHttp(unittest.TestCase):
    def call(self, response, statuses=(200,)):
        return request_json(
            Mock(return_value=response),
            "https://provider.invalid/orders/1",
            provider="test",
            resource_type="order",
            resource_id="1",
            success_statuses=statuses,
        )

    def test_200_and_206_are_successful(self):
        self.assertTrue(self.call(FakeResponse(200, {"id": 1})).ok)
        result = self.call(FakeResponse(206, {"id": 1}), (200, 206))
        self.assertTrue(result.ok)
        self.assertTrue(result.partial)

    def test_http_taxonomy(self):
        expected = {
            400: ("provider_parameter_error", False),
            401: ("credential_action_required", False),
            403: ("provider_access_forbidden", False),
            404: ("provider_resource_not_found", False),
            429: ("provider_rate_limited", True),
            500: ("provider_server_error", True),
        }
        for status, (error_type, retryable) in expected.items():
            with self.subTest(status=status):
                headers = {"Retry-After": "17"} if status == 429 else {}
                result = self.call(FakeResponse(status, text="provider error", headers=headers))
                self.assertEqual(result.error_type, error_type)
                self.assertEqual(result.retryable, retryable)
                if status == 429:
                    self.assertEqual(result.retry_after, 17)

    def test_timeout_network_and_invalid_json_are_retryable(self):
        timeout = request_json(
            Mock(side_effect=requests.Timeout("timeout")),
            "https://provider.invalid",
            provider="test",
            resource_type="order",
        )
        network = request_json(
            Mock(side_effect=requests.ConnectionError("offline")),
            "https://provider.invalid",
            provider="test",
            resource_type="order",
        )
        invalid = self.call(FakeResponse(200, json_error=ValueError("bad json")))
        self.assertEqual(timeout.error_type, "provider_timeout")
        self.assertEqual(network.error_type, "provider_network_error")
        self.assertEqual(invalid.error_type, "provider_invalid_response")
        self.assertTrue(timeout.retryable and network.retryable and invalid.retryable)


if __name__ == "__main__":
    unittest.main()
