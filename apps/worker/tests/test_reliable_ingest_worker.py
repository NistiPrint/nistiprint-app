import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from apps.worker import reliable_ingest_worker as worker


class FakeRedis:
    def __init__(self, value=None):
        self.value = value

    def get(self, _key):
        return self.value


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

    def test_invalid_n8n_verdict_is_audit_only_under_optional_policy(self):
        item = {"source": "shopee", "event_id": "optional"}
        redis = FakeRedis('{"signature_status":"discarded_invalid_signature"}')
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}):
            result, verdict_key = worker._signature_result(item, redis)
        self.assertEqual(result.status, "signature_unverified")
        self.assertTrue(result.valid)
        self.assertFalse(result.terminal)
        self.assertEqual(verdict_key, "np:ingest:signature:optional")

    def test_invalid_n8n_verdict_is_terminal_under_required_policy(self):
        item = {"source": "shopee", "event_id": "required"}
        redis = FakeRedis('{"signature_status":"discarded_invalid_signature"}')
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "required"}):
            result, _ = worker._signature_result(item, redis)
        self.assertEqual(result.status, "discarded_invalid_signature")
        self.assertFalse(result.valid)
        self.assertTrue(result.terminal)


if __name__ == "__main__":
    unittest.main()
