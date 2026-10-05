import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from nistiprint_shared.services import despacho_janela_service as svc


class WindowRecoveryTest(unittest.TestCase):
    def run_job(self, windows, *, close_error=None, insert_error=None, recalc_error=None):
        db = MagicMock()
        def rpc(name, params):
            if name == 'janelas_despacho_vencidas':
                return SimpleNamespace(execute=lambda: SimpleNamespace(data=windows))
            if name == 'despacho_fechar_corte' and close_error:
                raise close_error
            if name == 'despacho_recalcular_compromissos' and recalc_error:
                raise recalc_error
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=0))
        db.rpc.side_effect = rpc
        if insert_error:
            db.table.return_value.insert.return_value.execute.side_effect = insert_error
        with patch.object(svc, 'supabase_db', db):
            svc.fechar_janelas_despacho.run.__wrapped__()
        return db

    def window(self, kind='COLETA'):
        return {'integration_id': 1, 'modalidade_id': 2, 'tipo': kind, 'janela_em': '2026-10-02T14:00:00-03:00'}

    def test_empty_windows_retries_recalculation_before_checkpoint(self):
        db = self.run_job([])
        self.assertIn('despacho_recalcular_compromissos', [call.args[0] for call in db.rpc.call_args_list])
        db.table.return_value.update.assert_called_once()
        self.assertIn('ultima_consulta_em', db.table.return_value.update.call_args.args[0])

    def test_recalculation_failure_does_not_advance_checkpoint(self):
        db = self.run_job([], recalc_error=RuntimeError('Unavailable'))
        db.table.return_value.update.assert_not_called()

    def test_cut_failure_does_not_advance_checkpoint(self):
        db = self.run_job([self.window('CORTE')], close_error=RuntimeError('Unavailable'))
        db.table.return_value.update.assert_not_called()

    def test_collection_database_failure_does_not_advance_checkpoint(self):
        db = self.run_job([self.window()], insert_error=RuntimeError('Unavailable'))
        db.table.return_value.update.assert_not_called()

    def test_duplicate_collection_is_idempotent_and_advances_checkpoint(self):
        conflict = RuntimeError('Duplicate')
        conflict.code = '23505'
        db = self.run_job([self.window()], insert_error=conflict)
        db.table.return_value.update.assert_called_once()
