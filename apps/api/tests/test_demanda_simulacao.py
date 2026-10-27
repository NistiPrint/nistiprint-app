"""Percurso isolado: a máquina de estado só produz uma cópia do cenário."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.demanda_simulacao_state import create_state, display_state, transition  # noqa: E402


class DemandSimulationStateTest(unittest.TestCase):
    def setUp(self):
        self.orders = [{'id': 9, 'pedido_id': 9, 'numero_pedido': 'P-9'}]
        self.lines = [
            {'produto': 'Produto do pedido', 'sku': 'SKU-1', 'miolo': 'M1', 'quantidade': 3},
            {'produto': 'Linha manual', 'sku': 'MANUAL', 'quantidade': 2},
        ]
        self.draft = create_state(self.lines, self.orders, {'marketplace_nome': 'Loja'})

    def test_full_path_and_source_snapshot_remain_unchanged(self):
        published = transition(self.draft, 'publicar', {})
        first = published['itens'][0]['id']
        second = published['itens'][1]['id']
        produced = transition(published, 'producao', {'updates': [{
            'item_id': first,
            'producao_incremental': {'capas_impressas_qtd': 2, 'capas_produzidas_qtd': 1},
        }]})
        partially_finished = transition(produced, 'finalizar_item', {'item_id': first, 'quantidade': 2})
        partial_collection = transition(partially_finished, 'coletar', {'quantidade': 1})
        completed_first = transition(partial_collection, 'finalizar_item', {'item_id': first, 'quantidade': 1})
        completed = transition(completed_first, 'finalizar_item', {'item_id': second, 'quantidade': 2})
        collected = transition(completed, 'coletar', {'quantidade': 4})
        self.assertEqual(collected['status'], 'COLETADO')
        self.assertEqual(display_state({'id': 'sim', 'version': 7, 'state': collected})['quantidade_coletada_total'], 5)
        self.assertEqual(self.draft['status'], 'RASCUNHO')
        self.assertEqual(self.draft['itens'][0]['finalizados_qtd'], 0)
        self.assertEqual(self.orders, [{'id': 9, 'pedido_id': 9, 'numero_pedido': 'P-9'}])

    def test_invalid_operations_do_not_change_prior_state(self):
        published = transition(self.draft, 'publicar', {})
        first = published['itens'][0]['id']
        with self.assertRaises(ValueError):
            transition(published, 'producao', {'updates': [{
                'item_id': first, 'producao_incremental': {'capas_produzidas_qtd': 1},
            }]})
        with self.assertRaises(ValueError):
            transition(published, 'finalizar_item', {'item_id': first, 'quantidade': 4})
        with self.assertRaises(ValueError):
            transition(published, 'coletar', {'quantidade': 1})
        self.assertEqual(published['itens'][0]['capas_produzidas_qtd'], 0)

    def test_revert_before_collection_only(self):
        published = transition(self.draft, 'publicar', {})
        first = published['itens'][0]['id']
        finalized = transition(published, 'finalizar_item', {'item_id': first, 'quantidade': 1})
        reverted = transition(finalized, 'reverter_item', {'item_id': first})
        self.assertEqual(reverted['itens'][0]['finalizados_qtd'], 0)
        collected = transition(finalized, 'coletar', {'quantidade': 1})
        with self.assertRaises(ValueError):
            transition(collected, 'reverter_item', {'item_id': first})


if __name__ == '__main__':
    unittest.main()


class SimulationProjectionTest(unittest.TestCase):
    def _row(self, status):
        item = {'id': 'i1', 'sku': 'S', 'item_descricao': 'Livro', 'quantidade_total': 10,
                'capas_prontas_retirada_qtd': 6, 'miolos_prontos_retirada_qtd': 4,
                'expedicao_capas_retiradas_qtd': 1, 'expedicao_miolos_retirados_qtd': 0,
                'status_item': 'Em Andamento'}
        return {'id': 'sim-1', 'state': {'status': status, 'nome': 'Simulação · ML', 'itens': [item]}}

    def test_only_published_simulations_enter_planning(self):
        from routes.demanda_simulacao_state import simulation_demands
        self.assertEqual(simulation_demands([self._row('RASCUNHO'), self._row('COLETADO')]), [])
        demand, items = simulation_demands([self._row('EM_PRODUCAO')])[0]
        self.assertTrue(demand['simulacao'])
        self.assertEqual(len(items), 1)

    def test_consolidated_row_matches_view_shape(self):
        from routes.demanda_simulacao_state import simulation_consolidated
        row = simulation_consolidated([self._row('CONCLUIDO')])[0]
        self.assertEqual((row['match_disponivel'], row['trilha'], row['simulacao']), (4, 'NORMAL', True))
