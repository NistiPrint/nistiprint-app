"""Consistency checks for user-visible asynchronous operation state."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.database.supabase_db_service import supabase_db

with patch.object(supabase_db, 'table', return_value=MagicMock()):
    from nistiprint_shared.services.async_operation_service import AsyncOperationService
    import nistiprint_shared.services.async_operation_service as service_module


class TestAsyncOperationConsistency(unittest.TestCase):
    def _query(self, current, updated=None):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.maybe_single.return_value = query
        query.update.return_value = query
        if updated is None:
            query.execute.return_value = SimpleNamespace(data=current)
        else:
            query.execute.side_effect = [
                SimpleNamespace(data=current),
                SimpleNamespace(data=[updated]),
            ]
        return query

    def test_status_antigo_nao_reabre_operacao_em_andamento(self):
        current = {
            'id': 'op-1', 'owner_user_id': 7, 'status': 'EM_ANDAMENTO',
            'updated_at': '2026-10-08T10:00:00Z', 'progresso_atual': 8,
        }
        query = self._query(current)
        service = AsyncOperationService()
        with patch.object(service_module.supabase_db, 'table', return_value=query):
            result = service.update_operation('op-1', status='AGUARDANDO', progresso_atual=2)

        self.assertEqual(result, current)
        query.update.assert_not_called()

    def test_progresso_concorrente_nao_regride(self):
        current = {
            'id': 'op-1', 'owner_user_id': 7, 'status': 'EM_ANDAMENTO',
            'updated_at': '2026-10-08T10:00:00Z', 'progresso_atual': 8,
            'mensagem': '8 de 10 pedidos processados',
        }
        updated = {**current, 'updated_at': '2026-10-08T10:00:01Z'}
        query = self._query(current, updated)
        service = AsyncOperationService()
        with patch.object(service_module.supabase_db, 'table', return_value=query), patch.object(service, '_publish'):
            service.update_operation(
                'op-1', status='EM_ANDAMENTO', progresso_atual=3,
                mensagem='3 de 10 pedidos processados',
            )

        payload = query.update.call_args.args[0]
        self.assertEqual(payload['progresso_atual'], 8)
        self.assertEqual(payload['mensagem'], current['mensagem'])

    def test_notificacao_terminal_conta_falhas_no_plural(self):
        operation = {
            'id': 'op-2', 'owner_user_id': 7, 'status': 'CONCLUIDO',
            'dados_adicionais': {'sucesso': 3, 'falhas': 2},
        }
        service = AsyncOperationService()
        with patch.object(service_module.notification_service, 'create_notification', return_value='n-1') as create, patch.object(service, '_publish') as publish:
            service._notify_terminal(operation)

        self.assertEqual(create.call_args.kwargs['event_type'], 'operation.failed')
        self.assertEqual(create.call_args.kwargs['payload']['message'], '3 concluído(s) com sucesso; 2 com falha.')
        publish.assert_called_once()


if __name__ == '__main__':
    unittest.main()
