import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from nistiprint_shared.services import logistica_manutencao_service as svc


class LogisticsMaintenanceTest(unittest.TestCase):
    def test_invalid_schedule_does_not_become_a_day_off(self):
        for payload in ({}, {'schedule': []}, {'schedule': {'friday': {'work': 'false'}}},
                        {'schedule': {'friday': {'work': True, 'detail': [{'from': '25:00'}]}}}):
            with self.assertRaises(ValueError): svc.normalize_schedule(payload)

    def test_schedule_preserves_days_off_and_multiple_windows(self):
        payload = {'schedule': {'friday': {'work': True, 'detail': [
            {'from': '14:00:00', 'to': '15:00', 'cutoff': '13:00', 'milkrun_same_day': True},
            {'from': '19:00', 'to': '20:00'}]}, 'saturday': {'work': False}}}
        actual = svc.normalize_schedule(payload)
        self.assertEqual(len(actual['friday']['detail']), 2)
        self.assertEqual(actual['friday']['detail'][0]['from'], '14:00')
        self.assertFalse(actual['saturday']['work'])

    def test_retry_after_is_respected(self):
        now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
        self.assertEqual(svc.retry_at({'retry_after': 1800}, now), '2026-10-02T12:30:00+00:00')

    def test_partial_rule_update_omits_absent_fields_and_audits_actor(self):
        with patch.object(svc, 'rpc_data') as rpc:
            svc.salvar_regra({'ativo': False, 'id': 99, 'unknown': 'ignored'}, 12, '7')
        rpc.assert_called_once_with('logistica_salvar_regra', {'p_id': 12, 'p_dados': {'ativo': False}, 'p_ator': '7'})

    def test_pre_registered_identifier_normalizes_conditions(self):
        with patch.object(svc, 'rpc_data') as rpc:
            svc.associar({'module_id': 'mercadolivre', 'chave': ' new_type ', 'modalidade_id': 3,
                'condicoes': {'service': 'express', 'tags': ['fast', 'fast', ' priority ']}}, '7')
        self.assertEqual(rpc.call_args.args[1]['p_condicoes'], {'service': 'express', 'tags': ['fast', 'priority']})
        self.assertEqual(rpc.call_args.args[1]['p_chave'], 'new_type')

    def test_invalid_payload_is_rejected_before_transaction(self):
        with patch.object(svc, 'rpc_data') as rpc:
            for payload in ({'antecedencia_alerta_min': True}, {'ativo': 'false'}, {'modalidade_ids': [True]}):
                with self.assertRaises(ValueError): svc.salvar_regra(payload, 12)
            with self.assertRaises(ValueError): svc.associar({'module_id': 'mercadolivre', 'chave': 'new', 'condicoes': {'tags': [1]}})
        rpc.assert_not_called()
