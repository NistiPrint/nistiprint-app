import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from nistiprint_shared.services import logistica_sync_service as svc
from nistiprint_shared.services.marketplace_webhook_ingest_service import marketplace_webhook_ingest_service as ingest


def query(rows):
    q = MagicMock()
    for method in ('select', 'eq', 'in_', 'order', 'update', 'upsert'):
        getattr(q, method).return_value = q
    q.execute.return_value = SimpleNamespace(data=rows)
    return q


class ScheduleSyncTest(unittest.TestCase):
    def test_failure_preserves_cached_agenda_and_backoff(self):
        rules = query([{'marketplace_integration_id': 1, 'logistic_type': 'cross_docking'}])
        cache = query([{'agenda': {'friday': {'work': False}}, 'consultada_em': '2026-10-02T12:00:00Z'}])
        cursors = query([])
        db = MagicMock()
        db.table.side_effect = lambda name: {'regras_logisticas_integracao': rules, 'logistica_agendas': cache, 'logistica_sync_cursores': cursors}[name]
        with patch.object(svc, 'supabase_db', db), patch.object(svc, 'rpc_data', return_value=True), \
             patch.object(svc, '_integration', return_value={'id': 1}), \
             patch.object(svc.driver, 'get_shipping_user', return_value={'id': 123}), \
             patch.object(svc.driver, 'get_shipping_schedule', return_value={'error': 'Limite', 'status_code': 429, 'retry_after': 1800}):
            report = svc.sincronizar_agendas()
        saved = cache.upsert.call_args.args[0]
        self.assertNotIn('agenda', saved)
        self.assertNotIn('consultada_em', saved)
        self.assertEqual(saved['erro'], 'Limite')
        self.assertIsNotNone(saved['proxima_tentativa_em'])
        self.assertEqual(report['erros'], 1)
        self.assertTrue(any('proxima_tentativa_em' in c.args[0] for c in cursors.update.call_args_list))

    def test_multiorigin_account_stays_manual_with_reason(self):
        rules = query([{'marketplace_integration_id': 1, 'logistic_type': 'cross_docking'}])
        cache, cursor = query([]), query([])
        db = MagicMock()
        db.table.side_effect = lambda name: rules if name=='regras_logisticas_integracao' else cache if name=='logistica_agendas' else cursor
        with patch.object(svc, 'supabase_db', db), patch.object(svc, 'rpc_data', return_value=True), \
             patch.object(svc, '_integration', return_value={'id': 1}), \
             patch.object(svc.driver, 'get_shipping_user', return_value={'id': 123, 'tags': ['warehouse_management']}), \
             patch.object(svc.driver, 'get_shipping_schedule') as schedule:
            svc.sincronizar_agendas()
        schedule.assert_not_called()
        self.assertIn('multiplas origens', cache.upsert.call_args.args[0]['erro'])

    def test_unauthorized_call_renews_once_and_retries(self):
        call = MagicMock(side_effect=[{'error': 'Unauthorized', 'status_code': 401}, {'id': 123}])
        from nistiprint_shared.services.installed_integration_service import installed_integration_service
        with patch.object(installed_integration_service, 'renew_integration_token') as renew, \
             patch.object(svc, '_integration', return_value={'id': 1, 'access_token': 'new'}):
            result = svc._call({'id': 1, 'access_token': 'old'}, call)
        renew.assert_called_once()
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result, {'id': 123})


class ShipmentReconciliationTest(unittest.TestCase):
    def test_deduplicates_shipment_and_updates_all_orders_including_published(self):
        orders = query([{'id': 10, 'marketplace_integration_id': 1, 'marketplace_order_id': '100'},
                        {'id': 11, 'marketplace_integration_id': 1, 'marketplace_order_id': '101'}])
        mirror, cursor = query([{'shipment_id': 999}]), query([])
        db = MagicMock()
        db.table.side_effect = lambda name: {'pedidos': orders, 'pedidos_mercadolivre': mirror, 'logistica_sync_cursores': cursor}[name]
        with patch.object(svc, 'supabase_db', db), patch.object(svc, 'rpc_data', side_effect=lambda name, params: [10, 11] if name=='logistica_reservar_sync' else 2), \
             patch.object(svc, '_integration', return_value={'id': 1, 'config': {'user_id': 123}}), \
             patch.object(ingest, 'process', return_value={'status': 'success', 'pedido_ids': [10, 11]}) as process:
            report = svc.reconciliar_envios()
        process.assert_called_once()
        self.assertEqual(process.call_args.args[1]['resource'], '/shipments/999')
        self.assertEqual(report['pedidos'], 2)
        self.assertEqual(cursor.update.call_args.args[0], {'ultimo_id': 11, 'bloqueado_ate': None})
        self.assertIn([10, 11], [call.args[1] for call in orders.in_.call_args_list])

    def test_rate_limit_stops_batch_without_advancing_failed_order(self):
        orders = query([{'id': 10, 'marketplace_integration_id': 1, 'marketplace_order_id': '100'},
                        {'id': 11, 'marketplace_integration_id': 1, 'marketplace_order_id': '101'}])
        mirror, cursor = query([{'shipment_id': 999}]), query([])
        db = MagicMock()
        db.table.side_effect = lambda name: {'pedidos': orders, 'pedidos_mercadolivre': mirror, 'logistica_sync_cursores': cursor}[name]
        with patch.object(svc, 'supabase_db', db), patch.object(svc, 'rpc_data', side_effect=lambda name, params: [10, 11] if name=='logistica_reservar_sync' else 0), \
             patch.object(svc, '_integration', return_value={'id': 1, 'config': {'user_id': 123}}), \
             patch.object(ingest, 'process', return_value={'status': 'error', 'error_type': 'provider_rate_limited', 'retry_after': 1800}) as process:
            svc.reconciliar_envios()
        process.assert_called_once()
        self.assertEqual(cursor.update.call_args.args[0]['ultimo_id'], 9)
        self.assertTrue(any('proxima_tentativa_em' in call.args[0] for call in cursor.update.call_args_list))
