"""Fluxo producao -> alocacao na demanda -> saida fisica.

Alocar nao e sair. O botao [-] da tela de Controle de Producao reserva o
componente para o item da demanda: o disponivel cai, o saldo fisico permanece.
A saida fisica acontece uma unica vez, na reconciliacao disparada pela
finalizacao — que antes consome as reservas do item para nao produzir JIT um
segundo componente por cima do que ja estava separado.
"""

import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.demanda_alocacao.estoque import (
    demanda_alocacao_estoque_service,
)


class _RespostaFake:
    def __init__(self, data):
        self.data = data


class TestReservarAlocacaoParaDemanda(unittest.TestCase):
    def setUp(self):
        self.service = demanda_alocacao_estoque_service

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_reserva_soma_e_nao_da_saida(self, estoque_mock, db_mock):
        db_mock.execute_with_retry.return_value = _RespostaFake([])
        db_mock.table.return_value = MagicMock()

        resultado = self.service.reservar_alocacao_para_demanda(
            product_id=75,
            distributions=[
                {'item_id': 2719, 'quantidade': 3},
                {'item_id': 2720, 'quantidade': 2},
            ],
            demanda_id=138,
            deposito_id=1,
            user_id='op@nisti',
        )

        self.assertTrue(resultado['success'])
        self.assertEqual(resultado['quantidade_reservada'], 5.0)
        self.assertEqual(resultado['itens'], 2)

        # Reserva o total de uma vez, e NUNCA registra saida.
        estoque_mock.reservar_estoque.assert_called_once_with(75, 5.0, 1)
        estoque_mock.registrar_saida.assert_not_called()

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_distribuicao_vazia_nao_reserva(self, estoque_mock, db_mock):
        resultado = self.service.reservar_alocacao_para_demanda(
            product_id=75, distributions=[], demanda_id=138, deposito_id=1
        )

        self.assertFalse(resultado['success'])
        self.assertEqual(resultado['quantidade_reservada'], 0.0)
        estoque_mock.reservar_estoque.assert_not_called()

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_quantidade_zero_ou_negativa_e_descartada(self, estoque_mock, db_mock):
        db_mock.execute_with_retry.return_value = _RespostaFake([])
        db_mock.table.return_value = MagicMock()

        resultado = self.service.reservar_alocacao_para_demanda(
            product_id=75,
            distributions=[
                {'item_id': 1, 'quantidade': 0},
                {'item_id': 2, 'quantidade': -4},
                {'item_id': 3, 'quantidade': 2},
            ],
            demanda_id=138, deposito_id=1,
        )

        self.assertEqual(resultado['quantidade_reservada'], 2.0)
        self.assertEqual(resultado['itens'], 1)


class TestConsumirAlocacoesDoItem(unittest.TestCase):
    def setUp(self):
        self.service = demanda_alocacao_estoque_service

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_libera_reserva_e_marca_consumida(self, estoque_mock, db_mock):
        db_mock.execute_with_retry.side_effect = [
            _RespostaFake([
                {'id': 'a1', 'produto_id': '75', 'quantidade_alocada': 3},
                {'id': 'a2', 'produto_id': '75', 'quantidade_alocada': 2},
            ]),
            _RespostaFake([{'id': 'a1'}]),
            _RespostaFake([{'id': 'a2'}]),
        ]
        db_mock.table.return_value = MagicMock()

        total = self.service.consumir_alocacoes_do_item(2719)

        self.assertEqual(total, 5.0)
        self.assertEqual(estoque_mock.liberar_reserva.call_count, 2)
        estoque_mock.liberar_reserva.assert_any_call(75, 3.0, None)
        estoque_mock.liberar_reserva.assert_any_call(75, 2.0, None)

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_item_sem_alocacao_e_no_op(self, estoque_mock, db_mock):
        db_mock.execute_with_retry.return_value = _RespostaFake([])
        db_mock.table.return_value = MagicMock()

        total = self.service.consumir_alocacoes_do_item(999)

        self.assertEqual(total, 0.0)
        estoque_mock.liberar_reserva.assert_not_called()

    @patch('nistiprint_shared.services.demanda_alocacao.estoque.supabase_db')
    @patch('nistiprint_shared.services.demanda_alocacao.estoque.estoque_service')
    def test_falha_numa_alocacao_nao_derruba_as_outras(self, estoque_mock, db_mock):
        db_mock.execute_with_retry.side_effect = [
            _RespostaFake([
                {'id': 'a1', 'produto_id': '75', 'quantidade_alocada': 3},
                {'id': 'a2', 'produto_id': '76', 'quantidade_alocada': 2},
            ]),
            _RespostaFake([{'id': 'a2'}]),
        ]
        db_mock.table.return_value = MagicMock()
        estoque_mock.liberar_reserva.side_effect = [RuntimeError('boom'), None]

        total = self.service.consumir_alocacoes_do_item(2719)

        # A primeira falhou; a segunda foi adiante.
        self.assertEqual(total, 2.0)


if __name__ == '__main__':
    unittest.main()
