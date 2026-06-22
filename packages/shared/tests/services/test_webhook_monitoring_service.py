import json
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import redis_queue_tasks as rqt
from nistiprint_shared.services import webhook_monitoring_service as wms


class TestWebhookMonitoringService(unittest.TestCase):
    def test_get_event_redacts_sensitive_payload_fields(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'id': 10,
                'source': 'bling',
                'raw_payload': {
                    'data': {'id': 123},
                    'headers': {'authorization': 'Bearer secret'},
                    'access_token': 'token-value',
                },
            }
        ]

        with patch.object(wms.supabase_db, 'table', return_value=table):
            event = wms.WebhookMonitoringService().get_event(10)

        self.assertEqual(event['raw_payload']['headers']['authorization'], '[REDACTED]')
        self.assertEqual(event['raw_payload']['access_token'], '[REDACTED]')
        self.assertEqual(event['raw_payload']['data']['id'], 123)

    def test_reprocess_event_rejects_non_failed_status(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {'id': 10, 'last_status': 'success', 'raw_payload': {'data': {'id': 123}}}
        ]

        with patch.object(wms.supabase_db, 'table', return_value=table), \
             patch.object(wms, 'get_redis_client') as redis_client:
            result = wms.WebhookMonitoringService().reprocess_event(10)

        self.assertFalse(result['success'])
        self.assertEqual(result['status_code'], 400)
        redis_client.assert_not_called()

    def test_reprocess_event_queues_original_payload(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'id': 10,
                'last_status': 'failed',
                'raw_payload': {
                    'data': {'id': 123, 'numeroLoja': 'ABC'},
                    'last_error': 'old',
                },
            }
        ]

        update_table = MagicMock()
        update_table.update.return_value.eq.return_value.execute.return_value.data = [{'id': 10}]
        redis_client = MagicMock()

        with patch.object(wms.supabase_db, 'table', side_effect=[select_table, update_table]), \
             patch.object(wms, 'get_redis_client', return_value=redis_client), \
             patch.object(wms, 'get_now_iso', return_value='2026-06-12T12:00:00-03:00'):
            result = wms.WebhookMonitoringService().reprocess_event(10)

        self.assertTrue(result['success'])
        queued_payload = json.loads(redis_client.rpush.call_args.args[1])
        self.assertEqual(redis_client.rpush.call_args.args[0], wms.BLING_WEBHOOK_QUEUE)
        self.assertEqual(queued_payload['webhook_event_id'], 10)
        self.assertEqual(queued_payload['data']['numeroLoja'], 'ABC')
        self.assertNotIn('last_error', queued_payload)

    def test_reprocess_event_uses_source_specific_queue(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'id': 11,
                'source': 'shopee',
                'last_status': 'dead_letter',
                'raw_payload': {'order_sn': 'SN123'},
            }
        ]

        update_table = MagicMock()
        update_table.update.return_value.eq.return_value.execute.return_value.data = [{'id': 11}]
        redis_client = MagicMock()

        with patch.object(wms.supabase_db, 'table', side_effect=[select_table, update_table]), \
             patch.object(wms, 'get_redis_client', return_value=redis_client), \
             patch.object(wms, 'get_now_iso', return_value='2026-06-12T12:00:00-03:00'):
            result = wms.WebhookMonitoringService().reprocess_event(11)

        self.assertTrue(result['success'])
        self.assertEqual(result['queue'], rqt.SHOPEE_WEBHOOK_QUEUE)
        self.assertEqual(redis_client.rpush.call_args.args[0], rqt.SHOPEE_WEBHOOK_QUEUE)


class TestRedisQueueWebhookAttempts(unittest.TestCase):
    def test_create_webhook_attempt_increments_event_and_inserts_attempt(self):
        event_table = MagicMock()
        event_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            'attempt_count': 2
        }
        event_table.update.return_value.eq.return_value.execute.return_value.data = [{'id': 10}]

        attempts_table = MagicMock()
        attempts_table.insert.return_value.execute.return_value.data = [{'id': 77}]

        def table_side_effect(name):
            if name == 'webhook_events':
                return event_table
            if name == 'webhook_event_attempts':
                return attempts_table
            raise AssertionError(name)

        with patch.object(rqt.supabase_db, 'table', side_effect=table_side_effect), \
             patch.object(rqt, 'get_now_iso', return_value='2026-06-12T12:00:00-03:00'):
            attempt_id, attempt_number = rqt._create_webhook_attempt(
                10,
                correlation_id='4fc454c2-44d9-4afd-bb21-3e7fc3323c64',
                queue_name=rqt.BLING_WEBHOOK_QUEUE,
            )

        self.assertEqual(attempt_id, 77)
        self.assertEqual(attempt_number, 3)
        inserted = attempts_table.insert.call_args.args[0]
        self.assertEqual(inserted['webhook_event_id'], 10)
        self.assertEqual(inserted['attempt_number'], 3)
        self.assertEqual(inserted['status'], 'processing')

    def test_marketplace_consumer_acknowledges_head_only_after_success(self):
        redis_client = MagicMock()
        payload = {'order_sn': 'SN123', 'shop_id': 'SHOP1'}
        redis_client.set.return_value = True
        redis_client.lindex.side_effect = [json.dumps(payload), None]

        with patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, '_insert_webhook_event', return_value=10), \
             patch.object(rqt, '_create_webhook_attempt', return_value=(77, 1)), \
             patch.object(rqt, '_finish_webhook_attempt') as finish_attempt, \
             patch.object(rqt, '_update_webhook_event') as update_event, \
             patch.object(rqt.marketplace_webhook_ingest_service, 'process', return_value={
                 'status': 'success',
                 'pedido_id': 99,
                 'external_order_id': 'SN123',
             }):
            result = rqt._consume_marketplace_queue(
                'shopee',
                rqt.SHOPEE_WEBHOOK_QUEUE,
                rqt.SHOPEE_WEBHOOK_FALHAS,
                rqt.SHOPEE_WEBHOOK_DEAD_LETTER,
            )

        self.assertEqual(result['sent'], 1)
        self.assertFalse(result['blocked'])
        redis_client.lpop.assert_called_once_with(rqt.SHOPEE_WEBHOOK_QUEUE)
        redis_client.lset.assert_not_called()
        redis_client.rpush.assert_not_called()
        finish_attempt.assert_called_once()
        update_event.assert_called()

    def test_marketplace_consumer_keeps_failed_event_at_queue_head(self):
        redis_client = MagicMock()
        payload = {'order_sn': 'SN123', 'shop_id': 'SHOP1'}
        redis_client.set.return_value = True
        redis_client.lindex.return_value = json.dumps(payload)

        with patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, '_insert_webhook_event', return_value=10), \
             patch.object(rqt, '_create_webhook_attempt', return_value=(77, 1)), \
             patch.object(rqt, '_finish_webhook_attempt'), \
             patch.object(rqt, '_update_webhook_event'), \
             patch.object(rqt.marketplace_webhook_ingest_service, 'process', return_value={
                 'status': 'error',
                 'error_type': 'shopee_detail_unavailable',
                 'message': 'API indisponivel',
             }):
            result = rqt._consume_marketplace_queue(
                'shopee',
                rqt.SHOPEE_WEBHOOK_QUEUE,
                rqt.SHOPEE_WEBHOOK_FALHAS,
                rqt.SHOPEE_WEBHOOK_DEAD_LETTER,
            )

        self.assertEqual(result['sent'], 0)
        self.assertTrue(result['blocked'])
        redis_client.lpop.assert_not_called()
        redis_client.rpush.assert_not_called()
        redis_client.lset.assert_called_once()
        queue_name, index, serialized = redis_client.lset.call_args.args
        self.assertEqual(queue_name, rqt.SHOPEE_WEBHOOK_QUEUE)
        self.assertEqual(index, 0)
        rewritten = json.loads(serialized)
        self.assertEqual(rewritten['retry_count'], 1)
        self.assertEqual(rewritten['last_error_type'], 'shopee_detail_unavailable')
        self.assertEqual(rewritten['last_error'], 'API indisponivel')
        self.assertIn('next_attempt_after', rewritten)


if __name__ == '__main__':
    unittest.main()
