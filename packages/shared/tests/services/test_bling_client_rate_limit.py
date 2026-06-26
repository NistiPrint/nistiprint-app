import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.bling.bling_client import (
    BlingClient,
    BlingRateLimitedError,
)


class TestBlingClientRateLimit(unittest.TestCase):
    def _make_client(self):
        return BlingClient({
            'id': 99,
            'access_token': 'token-123456',
            'refresh_token': 'refresh',
            'expires_in': 3600,
            'client_id': 'cid',
            'client_secret': 'secret',
            'updated_at': '2026-06-26T10:00:00+00:00',
            'created_at': '2026-06-26T10:00:00+00:00',
            'platform_name': 'bling',
        })

    @patch.object(BlingClient, '_get_valid_token', return_value='token-123456')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.acquire')
    @patch('nistiprint_shared.services.bling.bling_client.requests.request')
    @patch('nistiprint_shared.services.bling.bling_client.time.sleep')
    def test_request_raises_rate_limited_after_http_429_retries(self, sleep_mock, request_mock, acquire_mock, _token_mock):
        client = self._make_client()
        acquire_mock.return_value = {'granted': True}

        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.text = '{"error": {"type": "TOO_MANY_REQUESTS"}}'
        request_mock.return_value = response

        with self.assertRaises(BlingRateLimitedError) as ctx:
            client._request('GET', 'pedidos/vendas/123')

        self.assertEqual(ctx.exception.error_type, 'rate_limited')
        self.assertEqual(request_mock.call_count, 3)
        self.assertGreaterEqual(sleep_mock.call_count, 2)

    @patch.object(BlingClient, '_get_valid_token', return_value='token-123456')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.acquire_order_lock')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.release_order_lock')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.get_cached_order_detail')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.cache_order_detail')
    @patch('nistiprint_shared.services.bling.bling_client.requests.request')
    @patch('nistiprint_shared.services.bling.bling_client.bling_rate_limit_coordinator.acquire')
    def test_get_order_uses_short_cache_to_avoid_duplicate_fetches(
        self,
        acquire_mock,
        request_mock,
        cache_write_mock,
        cache_read_mock,
        release_lock_mock,
        acquire_lock_mock,
        _token_mock,
    ):
        client = self._make_client()
        acquire_mock.return_value = {'granted': True}
        acquire_lock_mock.return_value = ('lock-key', 'lock-value')
        cache_read_mock.side_effect = [None, {'id': 123, 'numero': '456'}]

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'data': {'id': 123, 'numero': '456'}}
        request_mock.return_value = response

        first = client.get_order(123)
        second = client.get_order(123)

        self.assertEqual(first['numero'], '456')
        self.assertEqual(second['numero'], '456')
        request_mock.assert_called_once()
        cache_write_mock.assert_called_once()
        release_lock_mock.assert_called_once_with('lock-key', 'lock-value')


if __name__ == '__main__':
    unittest.main()
