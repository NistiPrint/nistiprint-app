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


if __name__ == '__main__':
    unittest.main()
