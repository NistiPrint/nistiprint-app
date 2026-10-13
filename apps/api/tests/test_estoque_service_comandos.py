"""Contratos dos adaptadores legados com o núcleo de estoque transacional."""

import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402
from nistiprint_shared.services.estoque_command_service import (  # noqa: E402
    EstoqueCommandConflict,
    EstoqueCommandOutcomeUnknown,
    EstoqueCommandService,
)

with patch.object(supabase_db, 'table'):
    from nistiprint_shared.services.estoque_service import EstoqueService  # noqa: E402
    from nistiprint_shared.services.product_service import product_service  # noqa: E402


class TestEstoqueServiceComandos(unittest.TestCase):
    def setUp(self):
        self.service = EstoqueService()

    def test_endpoint_v2_permanece_desabilitado_ate_habilitacao_explicita(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(EstoqueCommandService.is_enabled())
        for value in ('1', 'true', 'yes', 'on'):
            with self.subTest(value=value), patch.dict(os.environ, {'ESTOQUE_COMANDOS_V2_ATIVO': value}):
                self.assertTrue(EstoqueCommandService.is_enabled())
        for value in ('0', 'false', 'no', 'off', ''):
            with self.subTest(value=value), patch.dict(os.environ, {'ESTOQUE_COMANDOS_V2_ATIVO': value}):
                self.assertFalse(EstoqueCommandService.is_enabled())

    def test_validacao_de_elegibilidade_falha_fechada_se_a_leitura_do_produto_falhar(self):
        with patch.object(product_service, 'can_hold_stock', side_effect=RuntimeError('database unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Não foi possível confirmar'):
                self.service._validate_stock_eligibility(10)

    def test_hash_semantico_normaliza_quantidade_e_ordena_movimentos(self):
        service = EstoqueCommandService()
        operation_id = '00000000-0000-4000-8000-000000000010'
        movement_a = {'produto_id': 10, 'deposito_id': 7, 'tipo_movimentacao': 'SAIDA', 'quantidade': '1.00'}
        movement_b = {'produto_id': 11, 'deposito_id': 7, 'tipo_movimentacao': 'ENTRADA', 'quantidade': 2}
        response = SimpleNamespace(data=[{'status': 'CONFIRMADO'}])
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: response)) as rpc:
            service.execute_command({
                'operation_id': operation_id, 'command_type': 'TRANSFERENCIA',
                'source': {'source_id': 'transfer-1'}, 'movimentos': [movement_a, movement_b],
            }, {'id': 4}, allow_when_disabled=True)
            first_hash = rpc.call_args.args[1]['p_content_hash']
            service.execute_command({
                'operation_id': operation_id, 'command_type': 'TRANSFERENCIA',
                'source': {'source_id': 'transfer-1'},
                'movimentos': [dict(movement_b, quantidade='2.0000'), dict(movement_a, quantidade=1)],
            }, {'id': 4}, allow_when_disabled=True)

        self.assertEqual(rpc.call_count, 2)
        self.assertEqual(first_hash, rpc.call_args.args[1]['p_content_hash'])

    def test_timeout_retorna_resultado_incerto_com_mesma_identidade(self):
        service = EstoqueCommandService()
        operation_id = '00000000-0000-4000-8000-000000000011'
        command = {
            'operation_id': operation_id,
            'command_type': 'AJUSTE',
            'movimentos': [{'produto_id': 10, 'deposito_id': 7,
                            'tipo_movimentacao': 'ENTRADA', 'quantidade': 1}],
        }
        with patch.object(supabase_db, 'rpc', side_effect=TimeoutError('timeout apos envio')):
            with self.assertRaises(EstoqueCommandOutcomeUnknown) as caught:
                service.execute_command(command, allow_when_disabled=True)

        self.assertEqual(caught.exception.operation_id, operation_id)

    def test_reutilizacao_conflitante_nao_e_mascarada_como_timeout(self):
        service = EstoqueCommandService()
        command = {
            'operation_id': '00000000-0000-4000-8000-000000000012',
            'command_type': 'AJUSTE',
            'movimentos': [{'produto_id': 10, 'deposito_id': 7,
                            'tipo_movimentacao': 'ENTRADA', 'quantidade': 1}],
        }
        with patch.object(supabase_db, 'rpc', side_effect=Exception('23505 operation_id reutilizado com conteúdo diferente')):
            with self.assertRaises(EstoqueCommandConflict):
                service.execute_command(command, allow_when_disabled=True)

    def test_balanco_envia_saldo_observado_como_compare_and_swap(self):
        result = {'operation_id': 'op-1'}
        with patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command',
                   return_value=result) as execute, \
             patch.object(self.service, '_resolve_deposito', return_value=7), \
             patch.object(self.service, '_validate_stock_eligibility'), \
             patch.object(self.service, '_validate_sector_permission'):
            operation_id = self.service.registrar_balanco(
                10, 7, 5, expected_saldo=8, operation_id='00000000-0000-4000-8000-000000000001'
            )

        self.assertEqual(operation_id, 'op-1')
        command = execute.call_args.args[0]
        self.assertEqual(command['movimentos'][0]['expected_saldo'], 8)
        self.assertEqual(command['movimentos'][0]['quantidade'], 5)
        self.assertTrue(execute.call_args.kwargs['allow_when_disabled'])

    def test_transferencia_envia_duas_pernas_na_mesma_operacao(self):
        with patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command',
                   return_value={'operation_id': 'op-2'}) as execute, \
             patch.object(self.service, '_resolve_deposito', side_effect=[7, 8]), \
             patch.object(self.service, '_validate_stock_eligibility'), \
             patch.object(self.service, '_validate_sector_permission'):
            self.service.registrar_transferencia(10, 7, 8, 3, operation_id='00000000-0000-4000-8000-000000000002')

        command = execute.call_args.args[0]
        self.assertEqual(len(command['movimentos']), 2)
        self.assertEqual([m['quantidade'] for m in command['movimentos']], [-3, 3])
        self.assertEqual({m['deposito_id'] for m in command['movimentos']}, {7, 8})

    def test_reducao_de_progresso_nao_gera_entrada_fisica_automatica(self):
        with patch.object(self.service, 'registrar_entrada') as registrar_entrada, \
             patch.object(self.service, 'registrar_saida') as registrar_saida:
            with self.assertRaisesRegex(ValueError, 'REQUER_COMPENSACAO'):
                self.service.movimentar_por_delta(10, -2, demanda_id=15, item_id=4)

        registrar_entrada.assert_not_called()
        registrar_saida.assert_not_called()

    def test_lote_sem_identidade_ou_origem_falha_sem_rpc(self):
        with patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command') as execute:
            with self.assertRaisesRegex(ValueError, 'operation_id'):
                self.service.registrar_movimentacao_lote(
                    [{'produto_id': 10, 'quantidade': 1, 'tipo_movimento': 'ENTRADA'}],
                    usuario_id=4,
                    user_context={'id': 4, 'is_admin': True},
                )
            with self.assertRaisesRegex(ValueError, 'source_type e source_id'):
                self.service.registrar_movimentacao_lote(
                    [{'produto_id': 10, 'quantidade': 1, 'tipo_movimento': 'ENTRADA'}],
                    usuario_id=4,
                    user_context={'id': 4, 'is_admin': True},
                    operation_id='00000000-0000-4000-8000-000000000040',
                    source={},
                )

        execute.assert_not_called()

    def test_lote_usa_uma_rpc_para_todos_os_movimentos(self):
        operation_id = '00000000-0000-4000-8000-000000000041'
        result = {'operation_id': operation_id, 'status': 'CONFIRMADO', 'movimentos': [{'id': 1}, {'id': 2}]}
        movements = [
            {'produto_id': 10, 'quantidade': '1.2500', 'tipo_movimento': 'ENTRADA'},
            {'produto_id': 11, 'quantidade': 2, 'tipo_movimento': 'SAIDA', 'deposito_id': 8},
        ]
        with patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command',
                   return_value=result) as execute, \
             patch.object(self.service, '_validate_stock_eligibility') as eligible, \
             patch.object(self.service, '_validate_sector_permission') as permitted, \
             patch.object(self.service, '_resolve_deposito', side_effect=lambda deposito_id: deposito_id or 7):
            actual = self.service.registrar_movimentacao_lote(
                movements,
                usuario_id=4,
                user_context={'id': 4, 'is_admin': True},
                operation_id=operation_id,
                source={'source_type': 'MOVIMENTACAO_LOTE_MANUAL', 'source_id': operation_id},
            )

        self.assertEqual(actual, result)
        self.assertEqual(execute.call_count, 1)
        command = execute.call_args.args[0]
        self.assertEqual(command['command_type'], 'MOVIMENTACAO_LOTE')
        self.assertEqual(command['operation_id'], operation_id)
        self.assertEqual(command['source']['source_id'], operation_id)
        self.assertEqual(
            [(row['produto_id'], row['deposito_id'], row['quantidade']) for row in command['movimentos']],
            [(10, 7, '1.25'), (11, 8, '-2')],
        )
        self.assertEqual(eligible.call_count, 2)
        self.assertEqual(permitted.call_count, 2)

    def test_lote_invalido_nao_envia_parcialmente_os_itens_validos(self):
        with patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command') as execute, \
             patch.object(self.service, '_validate_stock_eligibility'), \
             patch.object(self.service, '_validate_sector_permission'), \
             patch.object(self.service, '_resolve_deposito', return_value=7):
            with self.assertRaisesRegex(ValueError, 'Tipo de movimento inválido'):
                self.service.registrar_movimentacao_lote(
                    [
                        {'produto_id': 10, 'quantidade': 1, 'tipo_movimento': 'ENTRADA'},
                        {'produto_id': 11, 'quantidade': 1, 'tipo_movimento': 'AJUSTE_DESCONHECIDO'},
                    ],
                    usuario_id=4,
                    user_context={'id': 4, 'is_admin': True},
                    operation_id='00000000-0000-4000-8000-000000000042',
                    source={'source_type': 'MOVIMENTACAO_LOTE_MANUAL', 'source_id': 'batch-42'},
                )

        execute.assert_not_called()

    def test_reserva_por_origem_chama_rpc_idempotente(self):
        response = SimpleNamespace(data=[{'status': 'CONFIRMADO', 'quantidade': 2}])
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: response)) as rpc, \
             patch.object(self.service, '_resolve_deposito', return_value=7):
            self.service.reservar_estoque(
                10, 2, 7, ordem_id='pedido-55', tipo_ordem='PEDIDO',
                idempotency_key='pedido:55:linha:1:reserva',
            )

        args = rpc.call_args.args
        params = rpc.call_args.args[1]
        self.assertEqual(args[0], 'executar_comando_reserva_estoque')
        self.assertEqual(params['p_action'], 'RESERVAR')
        self.assertEqual(params['p_source']['source_id'], 'pedido-55')
        self.assertEqual(params['p_produto_id'], 10)
        self.assertEqual(params['p_quantidade'], '2')

    def test_saida_reservada_baixa_saldo_e_reserva_no_mesmo_rpc(self):
        response = SimpleNamespace(data=[{'status': 'CONFIRMADO', 'movimento_id': 81}])
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: response)) as rpc, \
             patch.object(self.service, '_resolve_deposito', return_value=7), \
             patch.object(self.service, '_validate_stock_eligibility'), \
             patch.object(self.service, '_validate_sector_permission'):
            movement_id = self.service.confirmar_saida_reservada(
                10, 2, 7, ordem_id='pedido-55', tipo_ordem='PEDIDO',
                idempotency_key='pedido:55:linha:1:baixa',
            )

        self.assertEqual(movement_id, '81')
        self.assertEqual(rpc.call_args.args[1]['p_action'], 'CONSUMIR')

    def test_listagem_preserva_origem_e_nao_fabrica_origem_para_residuo(self):
        operational_table = MagicMock()
        stock_table = MagicMock()
        operational_table.select.return_value.order.return_value.range.return_value.execute.side_effect = [
            SimpleNamespace(data=[{
                'produto_id': 10, 'deposito_id': 7, 'origem_tipo': 'PEDIDO',
                'origem_id': 'pedido-55', 'operation_id': 'reserve-op',
                'quantidade': 5, 'quantidade_consumida': 2, 'quantidade_liberada': 1,
                'created_at': '2026-10-09T00:00:00Z',
            }]),
            SimpleNamespace(data=[]),
        ]
        stock_table.select.return_value.gt.return_value.execute.return_value = SimpleNamespace(data=[{
            'produto_id': 10, 'deposito_id': 7, 'reservado': 3,
        }])
        with patch.object(supabase_db, 'table', side_effect=lambda name: {
            'estoque_reservas_operacionais': operational_table,
            'estoque_atual': stock_table,
        }[name]):
            reservations = self.service.get_all_with_reservations()

        self.assertEqual(reservations[0]['reservado'], 3)
        self.assertEqual(reservations[0]['reservas'][0]['ordem_id'], 'pedido-55')
        self.assertEqual(reservations[0]['reservas'][0]['quantidade'], 2)
        self.assertEqual(reservations[0]['reservas'][1]['tipo_ordem'], 'SEM_ORIGEM')
        self.assertIsNone(reservations[0]['reservas'][1]['ordem_id'])


if __name__ == '__main__':
    unittest.main()
