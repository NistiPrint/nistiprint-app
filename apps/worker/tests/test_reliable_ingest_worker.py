import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from apps.worker import reliable_ingest_worker as worker


class FakeRedis:
    def get(self, _key):
        return None


class SignatureVerdictTest(unittest.TestCase):
    def test_recent_shopee_event_waits_for_post_ack_verdict(self):
        item = {
            "source": "shopee",
            "event_id": "recent",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 0,
        }
        with self.assertRaises(worker.SignatureVerdictPending):
            worker._signature_result(item, FakeRedis())

    def test_old_backlog_uses_configured_signature_policy_immediately(self):
        expected = worker.SignatureResult("signature_unverified", True, False)
        item = {
            "source": "shopee",
            "event_id": "old",
            "received_at": (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
            "attempt": 0,
        }
        with patch.object(worker, "validate_signature", return_value=expected) as validate:
            result, verdict_key = worker._signature_result(item, FakeRedis())
        self.assertIs(result, expected)
        self.assertIsNone(verdict_key)
        validate.assert_called_once_with(item)


if __name__ == "__main__":
    unittest.main()
