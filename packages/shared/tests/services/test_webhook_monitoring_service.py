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

    def test_reprocess_event_rejects_non_retryable_status(self):
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

    def test_reprocess_event_queues_original_payload_for_bling(self):
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

    def test_reprocess_event_queues_marketplace_event_id_only(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'id': 11,
                'source': 'shopee',
                'last_status': 'manual_intervention',
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
        queued_payload = json.loads(redis_client.rpush.call_args.args[1])
        self.assertEqual(queued_payload['webhook_event_id'], 11)
        self.assertNotIn('order_sn', queued_payload)


class TestRedisQueueWebhookIdentity(unittest.TestCase):
    def test_extract_webhook_identity_uses_source_specific_event_ids(self):
        bling_identity = rqt._extract_webhook_identity('bling', {
            'eventId': 'evt-bling-1',
            'companyId': 'company-1',
            'data': {'id': 123, 'numeroLoja': 'ABC'},
        })
        shopee_identity = rqt._extract_webhook_identity('shopee', {
            'event_id': 'evt-shopee-1',
            'order_sn': 'SN123',
            'shop_id': 'SHOP1',
        })
        meli_identity = rqt._extract_webhook_identity('mercadolivre', {
            'id': 987654,
            'resource': '/orders/26174897235',
            'user_id': 'SELLER1',
        })
        meli_fallback_identity = rqt._extract_webhook_identity('mercadolivre', {
            '_id': 'evt-meli-2',
            'resource': '/orders/26174897235',
            'user_id': 'SELLER1',
        })

        self.assertEqual(bling_identity['provider_event_id'], 'evt-bling-1')
        self.assertEqual(shopee_identity['provider_event_id'], 'evt-shopee-1')
        self.assertEqual(meli_identity['provider_event_id'], 987654)
        self.assertEqual(meli_fallback_identity['provider_event_id'], 'evt-meli-2')
        self.assertEqual(meli_identity['order_id'], '26174897235')


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

    def test_enqueue_marketplace_webhook_persists_event_and_pushes_wakeup(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        insert_table = MagicMock()
        insert_table.insert.return_value.execute.return_value.data = [{'id': 55}]
        redis_client = MagicMock()

        def table_side_effect(name):
            if name == 'webhook_events':
                if not hasattr(table_side_effect, 'called'):
                    table_side_effect.called = 0
                table_side_effect.called += 1
                return select_table if table_side_effect.called == 1 else insert_table
            raise AssertionError(name)

        with patch.object(rqt.supabase_db, 'table', side_effect=table_side_effect), \
             patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, 'generate_correlation_id', return_value='cid-1'), \
             patch.object(rqt, 'get_now', return_value=rqt.parse_datetime('2026-06-25T12:00:00+00:00')):
            result = rqt.enqueue_marketplace_webhook_event(
                'shopee',
                {'event_id': 'evt-1', 'order_sn': 'SN123', 'shop_id': 'SHOP1'},
            )

        self.assertEqual(result['event_id'], 55)
        self.assertTrue(result['queued'])
        queued = json.loads(redis_client.rpush.call_args.args[1])
        self.assertEqual(queued, {'webhook_event_id': 55})

    def test_enqueue_marketplace_webhook_deduplicates_by_provider_event_id(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {'id': 55, 'last_status': 'success', 'correlation_id': 'cid-existing'}
        ]
        redis_client = MagicMock()

        with patch.object(rqt.supabase_db, 'table', return_value=select_table), \
             patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, 'generate_correlation_id', return_value='cid-1'), \
             patch.object(rqt, 'get_now', return_value=rqt.parse_datetime('2026-06-25T12:00:00+00:00')):
            result = rqt.enqueue_marketplace_webhook_event(
                'shopee',
                {'event_id': 'evt-1', 'order_sn': 'SN123', 'shop_id': 'SHOP1'},
            )

        self.assertEqual(result['event_id'], 55)
        self.assertFalse(result['queued'])
        redis_client.rpush.assert_not_called()

    def test_get_or_create_webhook_event_reuses_existing_bling_event_id(self):
        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {'id': 77, 'last_status': 'success', 'correlation_id': 'cid-existing'}
        ]

        with patch.object(rqt.supabase_db, 'table', return_value=select_table):
            event_id, created, existing = rqt._get_or_create_webhook_event(
                {'eventId': 'evt-bling-1', 'data': {'id': 123, 'numeroLoja': 'ABC'}},
                source='bling',
                company_id='company-1',
                bling_id=123,
                numero_loja='ABC',
                correlation_id='cid-1',
                provider_event_id='evt-bling-1',
            )

        self.assertEqual(event_id, 77)
        self.assertFalse(created)
        self.assertEqual(existing['last_status'], 'success')

    def test_marketplace_consumer_processes_oldest_eligible_event_from_db(self):
        redis_client = MagicMock()
        redis_client.set.return_value = True
        redis_client.lpop.side_effect = [json.dumps({'webhook_event_id': 10}), None]
        pending_event = {
            'id': 10,
            'raw_payload': {'order_sn': 'SN123', 'shop_id': 'SHOP1'},
            'numero_loja': 'SN123',
            'company_id': 'SHOP1',
            'last_status': 'pending',
        }

        with patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, '_load_next_marketplace_event', side_effect=[pending_event, None]), \
             patch.object(rqt, '_has_pending_marketplace_events', return_value=False), \
             patch.object(rqt, '_create_webhook_attempt', return_value=(77, 1)), \
             patch.object(rqt, '_mark_marketplace_processing') as mark_processing, \
             patch.object(rqt, '_finish_webhook_attempt') as finish_attempt, \
             patch.object(rqt, '_finalize_marketplace_success') as finalize_success, \
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
        mark_processing.assert_called_once_with(10, unittest.mock.ANY)
        finish_attempt.assert_called_once()
        finalize_success.assert_called_once()

    def test_marketplace_consumer_keeps_retry_on_same_event_without_reordering_other_orders(self):
        redis_client = MagicMock()
        redis_client.set.return_value = True
        redis_client.lpop.side_effect = [json.dumps({'webhook_event_id': 10}), None]
        pending_event = {
            'id': 10,
            'raw_payload': {'order_sn': 'SN123', 'shop_id': 'SHOP1'},
            'numero_loja': 'SN123',
            'company_id': 'SHOP1',
            'last_status': 'pending',
            'attempt_count': 1,
            'retry_expires_at': '2026-07-02T12:00:00+00:00',
        }

        with patch.object(rqt, 'get_redis_client', return_value=redis_client), \
             patch.object(rqt, '_load_next_marketplace_event', side_effect=[pending_event, None]), \
             patch.object(rqt, '_has_pending_marketplace_events', return_value=True), \
             patch.object(rqt, '_create_webhook_attempt', return_value=(77, 2)), \
             patch.object(rqt, '_mark_marketplace_processing'), \
             patch.object(rqt, '_finish_webhook_attempt') as finish_attempt, \
             patch.object(rqt, '_schedule_marketplace_retry', return_value='pending_retry') as schedule_retry, \
             patch.object(rqt.marketplace_webhook_ingest_service, 'process', return_value={
                 'status': 'error',
                 'error_type': 'bling_order_not_found',
                 'message': 'Pedido ainda nao encontrado no Bling',
             }):
            result = rqt._consume_marketplace_queue(
                'shopee',
                rqt.SHOPEE_WEBHOOK_QUEUE,
                rqt.SHOPEE_WEBHOOK_FALHAS,
                rqt.SHOPEE_WEBHOOK_DEAD_LETTER,
            )

        self.assertEqual(result['sent'], 0)
        self.assertTrue(result['blocked'])
        schedule_retry.assert_called_once()
        finish_attempt.assert_called_once()
        redis_client.rpush.assert_not_called()


    def test_marketplace_consumer_passes_retry_after_from_rate_limit_result(self):
        redis_client = MagicMock()
        redis_client.set.return_value = True
        redis_client.lpop.side_effect = [json.dumps({'webhook_event_id': 10}), None]
        pending_event = {
            'id': 10,
            'raw_payload': {'resource': '/orders/26174897235', 'user_id': 'SHOP1'},
            'numero_loja': '26174897235',
            'company_id': 'SHOP1',
            'last_status': 'pending',
            'attempt_count': 1,
            'retry_expires_at': '2026-07-02T12:00:00+00:00',
        }

        with patch.object(rqt, 'get_redis_client', return_value=redis_client),              patch.object(rqt, '_load_next_marketplace_event', side_effect=[pending_event, None]),              patch.object(rqt, '_has_pending_marketplace_events', return_value=True),              patch.object(rqt, '_create_webhook_attempt', return_value=(77, 2)),              patch.object(rqt, '_mark_marketplace_processing'),              patch.object(rqt, '_finish_webhook_attempt'),              patch.object(rqt, '_schedule_marketplace_retry', return_value='pending_retry') as schedule_retry,              patch.object(rqt.marketplace_webhook_ingest_service, 'process', return_value={
                 'status': 'error',
                 'error_type': 'bling_rate_limited',
                 'message': 'Limite de requisicoes do Bling atingido',
                 'retry_after': 3,
             }):
            rqt._consume_marketplace_queue(
                'mercadolivre',
                rqt.MERCADOLIVRE_WEBHOOK_QUEUE,
                rqt.MERCADOLIVRE_WEBHOOK_FALHAS,
                rqt.MERCADOLIVRE_WEBHOOK_DEAD_LETTER,
            )

        self.assertEqual(schedule_retry.call_args.kwargs['retry_after'], 3)


if __name__ == '__main__':
    unittest.main()

