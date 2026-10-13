"""Sanitized contract fixtures based on active n8n webhook envelopes."""

import hashlib
import json
import unittest
from pathlib import Path

from apps.worker import reliable_ingest_worker
from nistiprint_shared.services.reliable_ingest_service import extract_identity


FIXTURES_PATH = Path(__file__).parent / "fixtures" / "n8n_webhook_envelopes.json"
EXPECTED_MELI_TOPICS = {"orders_v2", "items", "shipments", "payments", "messages"}


def _envelope_from_fixture(fixture):
    payload = fixture["parsed_payload"]
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    envelope = {
        "schema_version": 1,
        "event_id": f"fixture-{fixture['name']}",
        "source": fixture["source"],
        "received_at": "2026-10-10T12:00:00Z",
        "headers": fixture["headers"],
        "raw_body": raw_body,
        "parsed_payload": payload,
        "body_sha256": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
        "provider_delivery_id": fixture["provider_delivery_id"],
        "payload_size": len(raw_body.encode("utf-8")),
        "oversized": False,
    }
    if fixture["source"] == "mercadolivre":
        envelope.update({
            "account_id": str(payload["user_id"]),
            "application_id": str(payload["application_id"]),
            "provider_topic": payload["topic"],
            "route_hint": [],
        })
    return envelope


class N8nEnvelopeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))

    def test_fixtures_cover_active_sources_and_mercadolivre_topics(self):
        sources = {fixture["source"] for fixture in self.fixtures}
        topics = {
            fixture["provider_topic"] for fixture in self.fixtures
            if fixture["source"] == "mercadolivre"
        }
        self.assertEqual(sources, {"bling", "shopee", "mercadolivre"})
        self.assertEqual(topics, EXPECTED_MELI_TOPICS)

    def test_envelope_fields_hash_and_identity_match_each_provider_contract(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                envelope = _envelope_from_fixture(fixture)
                self.assertEqual(set(envelope), set(fixture["expected_envelope_keys"]))
                self.assertEqual(set(envelope["parsed_payload"]), set(fixture["expected_payload_keys"]))
                self.assertEqual(json.loads(envelope["raw_body"]), envelope["parsed_payload"])
                self.assertEqual(
                    envelope["body_sha256"],
                    hashlib.sha256(envelope["raw_body"].encode("utf-8")).hexdigest(),
                )
                self.assertEqual(envelope["payload_size"], len(envelope["raw_body"].encode("utf-8")))

                identity = extract_identity(envelope)
                self.assertEqual(identity["provider_event_id"], fixture["provider_delivery_id"])
                self.assertEqual(identity["dedupe_scope"], fixture["expected_scope"])
                self.assertEqual(identity["resolved_order_id"], fixture["expected_order_id"])

    def test_mercadolivre_messages_route_to_chat_and_other_topics_route_to_orders(self):
        for fixture in self.fixtures:
            if fixture["source"] != "mercadolivre":
                continue
            with self.subTest(topic=fixture["provider_topic"]):
                envelope = _envelope_from_fixture(fixture)
                self.assertEqual(
                    reliable_ingest_worker._is_chat(envelope),
                    fixture["provider_topic"] == "messages",
                )


if __name__ == "__main__":
    unittest.main()
