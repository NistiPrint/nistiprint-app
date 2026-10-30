import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from apps.worker import reliable_ingest_worker as worker


class FakeRedis:
    def __init__(self, value=None):
        self.value = value

    def get(self, _key):
        return self.value

    def delete(self, _key):
        self.value = None


class SignatureVerdictTest(unittest.TestCase):
    def test_unsupported_webhook_is_finalized_and_acknowledged_without_retry(self):
        item = {'webhook_event_id':123,'event_id':'ignored-topic'}
        result = {'status':'skipped','event_status':'skipped_unsupported_topic','retryable':False}
        client = FakeRedis()
        with patch.object(worker,'claim',return_value=item), \
             patch.object(worker,'finalize_event') as finalize, \
             patch.object(worker,'complete',return_value=True) as complete, \
             patch.object(worker,'_retry') as failure:
            worker._consume_once('ready','processing',lambda _:result,client=client)
        finalize.assert_called_once_with(123,'skipped_unsupported_topic',result=result)
        complete.assert_called_once_with(item,'processing',client)
        failure.assert_not_called()

    def test_shutdown_finishes_current_iteration_and_stops_new_claims(self):
        worker.SHUTDOWN_REQUESTED.clear()
        client = FakeRedis()

        def finish_current(_client):
            worker.SHUTDOWN_REQUESTED.set()
            return True

        with patch.object(worker, "redis_client", return_value=client), \
                patch.object(worker, "_heartbeat"), \
                patch.object(worker, "route_once", side_effect=finish_current) as route:
            worker.run("router")

        route.assert_called_once_with(client)
        worker.SHUTDOWN_REQUESTED.clear()

    def test_private_mercadolivre_message_topic_routes_to_chat_with_nested_payload(self):
        item = {"source": "mercadolivre", "parsed_payload": {
            "topic": "orders_v2", "data": {"topic": "messages"},
        }}
        self.assertTrue(worker._is_chat(item))

    def test_mercadolivre_other_topic_stays_on_order_route(self):
        item = {"source": "mercadolivre", "parsed_payload": {
            "topic": "orders_v2", "data": {"id": "123"},
        }}
        self.assertFalse(worker._is_chat(item))

    def test_shopee_chat_routing_still_uses_existing_adapter(self):
        adapter = type("Adapter", (), {"parse_webhook": lambda _self, _payload:
                                      type("Result", (), {"classification": "chat"})()})()
        with patch("nistiprint_shared.services.marketplace_adapters.shopee_adapter", adapter):
            self.assertTrue(worker._is_chat({"source": "shopee", "parsed_payload": {}}))

    def test_shopee_chat_keeps_existing_ingest_path(self):
        expected = {"status": "success", "event_status": "chat_persisted"}
        item = {"source": "shopee", "parsed_payload": {"topic": "shopee_chat"},
                "webhook_event_id": 55}
        with patch("nistiprint_shared.services.shopee_chat_service.shopee_chat_ingest_service.process",
                   return_value=expected) as shopee_process, \
             patch("nistiprint_shared.services.mercadolivre_personalization_service.enqueue_notification") as meli_enqueue:
            result = worker._process_chat(item)
        self.assertEqual(result, expected)
        shopee_process.assert_called_once_with(item["parsed_payload"], webhook_event_id=55)
        meli_enqueue.assert_not_called()

    def test_mercadolivre_chat_persists_inbox_then_dispatches_shared_celery_function(self):
        expected = {"status": "success", "identity_status": "matched", "inbox_id": 99}
        item = {"source": "mercadolivre", "parsed_payload": {"topic": "messages"},
                "webhook_event_id": 77}
        with patch("nistiprint_shared.services.mercadolivre_personalization_service.enqueue_notification",
                   return_value=expected) as enqueue, \
             patch("nistiprint_shared.services.celery_app.celery_app.send_task") as send_task:
            result = worker._process_chat(item)
        self.assertEqual(result, expected)
        enqueue.assert_called_once_with(item["parsed_payload"], webhook_event_id=77)
        send_task.assert_called_once_with("mercadolivre.chat.process_inbox", queue="celery")

    def test_validated_404_retries_only_inside_short_window(self):
        recent = {
            "event_id": "recent-404",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 0,
        }
        error = RuntimeError("not found")
        error.error_type = "provider_resource_not_found"
        error.retryable = False
        with patch.object(worker, "schedule_retry", return_value=True) as schedule, \
             patch.object(worker, "move_to_dlq") as dlq:
            worker._retry(recent, "processing", object(), error)
        schedule.assert_called_once()
        dlq.assert_not_called()

        expired = {
            "event_id": "expired-404",
            "received_at": (
                datetime.now(timezone.utc) - timedelta(minutes=6)
            ).isoformat(),
            "attempt": 0,
        }
        with patch.object(worker, "schedule_retry") as schedule, \
             patch.object(worker, "move_to_dlq", return_value=True) as dlq:
            worker._retry(expired, "processing", object(), error)
        schedule.assert_not_called()
        dlq.assert_called_once()

    def test_terminal_provider_error_does_not_retry(self):
        item = {
            "event_id": "bad-resource",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 0,
        }
        error = RuntimeError("bad parameter")
        error.error_type = "provider_parameter_error"
        error.retryable = False
        with patch.object(worker, "schedule_retry") as schedule, \
             patch.object(worker, "move_to_dlq", return_value=True) as dlq:
            worker._retry(item, "processing", object(), error)
        schedule.assert_not_called()
        dlq.assert_called_once()

    def test_recent_shopee_event_waits_for_post_ack_verdict(self):
        item = {
            "source": "shopee",
            "event_id": "recent",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 0,
        }
        with self.assertRaises(worker.SignatureVerdictPending):
            worker._signature_result(item, FakeRedis())

    def test_old_backlog_without_n8n_verdict_is_quarantined_when_required(self):
        item = {
            "source": "shopee",
            "event_id": "old",
            "received_at": (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
            "attempt": 0,
        }
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "required"}), \
             patch.object(worker, "validate_signature") as validate:
            result, verdict_key = worker._signature_result(item, FakeRedis())
        self.assertEqual(result.status, "discarded_signature_unverifiable")
        self.assertFalse(result.valid)
        self.assertTrue(result.terminal)
        self.assertIsNone(verdict_key)
        validate.assert_not_called()

    def test_unverified_n8n_verdict_passes_under_optional_policy(self):
        item = {"source": "shopee", "event_id": "unverified"}
        redis = FakeRedis('{"signature_status":"signature_unverified"}')
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}):
            with patch.object(worker, "validate_signature") as validate:
                result, verdict_key = worker._signature_result(item, redis)
        self.assertEqual(result.status, "signature_unverified")
        self.assertTrue(result.valid)
        self.assertFalse(result.terminal)
        self.assertEqual(verdict_key, "np:ingest:signature:unverified")
        validate.assert_not_called()

    def test_audit_hmac_mismatch_passes_under_observe_policy(self):
        item = {"source": "shopee", "event_id": "observed-invalid"}
        redis = FakeRedis(
            '{"signature_status":"signature_unverified",'
            '"signature_reason":"hmac_mismatch"}'
        )
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "observe"}):
            result, _ = worker._signature_result(item, redis)
        self.assertEqual(result.status, "signature_invalid_observed")
        self.assertTrue(result.valid)
        self.assertFalse(result.terminal)

    def test_missing_verdict_falls_back_to_optional_signature_validation(self):
        item = {
            "source": "shopee",
            "event_id": "old-unverified",
            "received_at": (
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
            "attempt": 3,
        }
        expected = worker.SignatureResult("signature_unverified", True, False, "no_usable_secret")
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}), \
             patch.object(worker, "validate_signature", return_value=expected) as validate:
            result, verdict_key = worker._signature_result(item, FakeRedis())
        self.assertEqual(result, expected)
        self.assertIsNone(verdict_key)
        validate.assert_called_once_with(item)

    def test_unverified_shopee_event_is_forwarded_under_optional_policy(self):
        item = {
            "source": "shopee",
            "event_id": "unverified-route",
            "webhook_event_id": 123,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "attempt": 3,
        }
        redis = FakeRedis('{"signature_status":"signature_unverified"}')
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}), \
             patch.object(worker, "claim", return_value=item), \
             patch.object(worker, "record_signature_result") as record_signature, \
             patch.object(worker, "finalize_event") as finalize, \
             patch.object(worker, "complete", return_value=True) as complete, \
             patch.object(worker, "_is_chat", return_value=False), \
             patch.object(worker, "forward", return_value=True) as forward:
            self.assertTrue(worker.route_once(redis))
        record_signature.assert_called_once()
        self.assertEqual(record_signature.call_args.args[1].status,
                         "signature_unverified")
        finalize.assert_not_called()
        complete.assert_not_called()
        forward.assert_called_once_with(
            item, worker.INBOX_PROCESSING, worker.ORDERS_READY, redis
        )

    def test_invalid_n8n_verdict_is_quarantined_under_optional_policy(self):
        item = {"source": "shopee", "event_id": "optional"}
        redis = FakeRedis('{"signature_status":"discarded_invalid_signature"}')
        with patch.dict("os.environ", {"INGEST_SIGNATURE_POLICY_SHOPEE": "optional"}):
            result, verdict_key = worker._signature_result(item, redis)
        self.assertEqual(result.status, "discarded_invalid_signature")
        self.assertFalse(result.valid)
        self.assertTrue(result.terminal)
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
