import unittest
from unittest.mock import patch

from nistiprint_shared.services.mercadolivre_rate_limit import (
    MercadoLivreRateLimitCoordinator,
    MercadoLivreRateLimitWait,
)


class FakeRedis:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def eval(self, script, key_count, *args):
        self.calls.append((script, key_count, args))
        return next(self.responses)


class MercadoLivreRateLimitTests(unittest.TestCase):
    def test_request_slot_is_limited_by_account_and_global_bucket(self):
        client = FakeRedis([[1, 0]])
        MercadoLivreRateLimitCoordinator(client).acquire(27, "messages")
        _, key_count, args = client.calls[0]
        self.assertEqual(key_count, 2)
        self.assertEqual(args[0], "mercadolivre:api:rate:27")
        self.assertEqual(args[1], "mercadolivre:api:rate:global")

    def test_timeout_returns_retry_after_instead_of_bypassing_limit(self):
        client = FakeRedis([[0, 500]])
        coordinator = MercadoLivreRateLimitCoordinator(client)
        with patch("nistiprint_shared.services.mercadolivre_rate_limit.ACQUIRE_TIMEOUT_MS", 1):
            with self.assertRaises(MercadoLivreRateLimitWait) as caught:
                coordinator.acquire(27, "messages")
        self.assertEqual(caught.exception.retry_after, 1.0)


if __name__ == "__main__":
    unittest.main()
