import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from nistiprint_shared.services.reliable_ingest_queue import build_envelope
from nistiprint_shared.services.reliable_ingest_service import extract_identity, validate_signature


class ReliableIngestSignatureTest(unittest.TestCase):
    def test_bling_validates_exact_raw_body(self):
        raw, secret = '{ "eventId": "1" }', "secret"
        signature = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        envelope = build_envelope("bling", json.loads(raw), raw_body=raw,
                                  headers={"x-bling-signature-256": signature})
        with patch.dict(os.environ, {"INGEST_SIGNATURE_POLICY_BLING": "required",
                                    "INGEST_WEBHOOK_SECRETS_BLING": secret}):
            result = validate_signature(envelope)
        self.assertTrue(result.valid)
        self.assertEqual(result.status, "signature_valid")

    def test_invalid_signature_is_terminal_even_in_optional_rollout(self):
        envelope = build_envelope("bling", {"eventId": "1"},
                                  headers={"x-bling-signature-256": "bad"})
        with patch.dict(os.environ, {"INGEST_SIGNATURE_POLICY_BLING": "optional",
                                    "INGEST_WEBHOOK_SECRETS_BLING": "secret"}):
            result = validate_signature(envelope)
        self.assertTrue(result.terminal)
        self.assertEqual(result.status, "discarded_invalid_signature")

    def test_missing_material_can_be_observed_during_rollout(self):
        envelope = build_envelope("shopee", {"code": 3})
        with patch.dict(os.environ, {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}, clear=False):
            result = validate_signature(envelope)
        self.assertTrue(result.valid)
        self.assertEqual(result.status, "signature_unverified")

    def test_chat_message_id_is_primary_dedupe_key(self):
        payload = {"code": 10, "shop_id": 7, "data": {"type": "message", "content": {
            "message_id": "2427073026633056625", "shop_id": 7, "conversation_id": "10"}}}
        identity = extract_identity(build_envelope("shopee", payload))
        self.assertEqual(identity["dedupe_key"], "provider:2427073026633056625")
        self.assertEqual(identity["dedupe_scope"], "7")


if __name__ == "__main__": unittest.main()
