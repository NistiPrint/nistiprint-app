"""Contrato Python com a leitura canônica da ficha efetiva no banco."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, 'table', return_value=MagicMock()):
    from nistiprint_shared.models.bom import BOMItem  # noqa: E402
    from nistiprint_shared.services.bom_service import BomService  # noqa: E402
    from nistiprint_shared.services.estoque_service import EstoqueService  # noqa: E402
    from nistiprint_shared.services.motor_reconciliacao_estoque import (  # noqa: E402
        IntencaoItem, MotorReconciliacaoEstoque,
    )


class TestBomEffective(unittest.TestCase):
    def setUp(self):
        with patch.object(supabase_db, 'table', return_value=MagicMock()):
            self.service = BomService()

    def test_single_read_preserves_group_and_line_origin(self):
        rows = [
            {'id': 10, 'produto_pai_id': 100, 'componente_id': 1, 'quantidade_necessaria': 1,
             'unidade_medida': 'un', 'grupo': 'CAPA', 'is_inherited': True},
            {'id': 11, 'produto_pai_id': 101, 'componente_id': 2, 'quantidade_necessaria': 2,
             'unidade_medida': 'un', 'grupo': 'CONTRA', 'is_inherited': False},
        ]
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))) as rpc:
            result = self.service.get_bom_for_produto(101)
        self.assertEqual([(r.group, r.origin) for r in result], [('CAPA', 'herdada'), ('CONTRA', 'propria')])
        rpc.assert_called_once_with('bom_efetiva_produto', {'p_produto_id': 101})

    def test_batch_read_uses_the_same_effective_bom_function(self):
        rows = [{'produto_id': 101, 'id': 12, 'produto_pai_id': 101, 'componente_id': 3,
                 'quantidade_necessaria': 1, 'unidade_medida': 'un', 'grupo': 'MIOLO', 'is_inherited': True}]
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))) as rpc:
            result = self.service.get_bom_for_multiple_products([101, '101', 'bad'])
        self.assertEqual(result[101][0].group, 'MIOLO')
        self.assertTrue(result[101][0].is_inherited)
        rpc.assert_called_once_with('bom_efetiva_produtos', {'p_produto_ids': [101]})

    def test_recursive_explosion_reports_an_indirect_cycle_with_path(self):
        a_to_b = [BOMItem(2, 1)]
        b_to_a = [BOMItem(1, 1)]
        with patch.object(self.service, 'get_bom_for_produto', side_effect=[a_to_b, b_to_a, b_to_a, a_to_b]):
            with self.assertRaisesRegex(ValueError, r'BOM_CYCLE: 1 -> 2 -> 1'):
                self.service.get_full_bom_explosion(1)

    def test_depth_limit_is_an_error_and_never_returns_a_truncated_explosion(self):
        with patch.object(self.service, 'get_bom_for_produto', return_value=[BOMItem(2, 1)]):
            with self.assertRaisesRegex(ValueError, 'BOM_DEPTH_LIMIT'):
                self.service.get_full_bom_explosion(1, max_depth=1)

    def test_effective_graph_preserves_intermediates_and_line_origin(self):
        rows = {
            1: [BOMItem(2, 2, is_inherited=True, group='KIT', line_id=11, produto_pai_id=9)],
            2: [BOMItem(3, 0.5, is_inherited=False, group='MIOLO', line_id=12, produto_pai_id=2)],
            3: [],
        }
        with patch.object(self.service, 'get_bom_for_multiple_products', side_effect=lambda ids: {pid: rows[pid] for pid in ids}), \
             patch('nistiprint_shared.services.bom_service.supabase_db.table') as table:
            table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
            graph = self.service.load_effective_graph([1])
        self.assertEqual(graph['nodes']['1']['componentes'][0]['componente_id'], 2)
        self.assertTrue(graph['nodes']['1']['componentes'][0]['is_inherited'])
        self.assertEqual(graph['nodes']['2']['componentes'][0]['componente_id'], 3)

    def test_effective_graph_rejects_cycles_before_inventory_execution(self):
        graph = {'roots': [1], 'nodes': {
            '1': {'componentes': [{'componente_id': 2, 'quantidade_necessaria': '1'}]},
            '2': {'componentes': [{'componente_id': 1, 'quantidade_necessaria': '1'}]},
        }}
        with self.assertRaisesRegex(ValueError, 'BOM_CYCLE: 1 -> 2 -> 1'):
            self.service.validate_effective_graph(graph)

    def test_immutable_explosion_keeps_decimal_totals_exact(self):
        version = {'produto_id': 1, 'graph': {'roots': [1], 'nodes': {
            '1': {'componentes': [{'componente_id': 2, 'quantidade_necessaria': '0.1'}]},
            '2': {'componentes': [{'componente_id': 3, 'quantidade_necessaria': '0.3'}]},
            '3': {'componentes': [], 'conversoes': []},
        }}}
        result = self.service.explode_effective_version(version, '3')
        self.assertEqual(result[0]['quantidade_total'], '0.09')

    def test_producao_avulsa_emite_entrada_e_insumos_no_mesmo_comando(self):
        stock = EstoqueService()
        version = {'id': 'version-1', 'content_hash': 'hash-1', 'graph': {'nodes': {
            '1': {'componentes': [{'componente_id': 2, 'quantidade_necessaria': '0.25',
                                   'unidade_medida': 'un'}]},
        }}}
        result = {'movimentos': [{'movimento_id': 44, 'produto_id': 1, 'tipo_movimentacao': 'ENTRADA'}]}
        with patch('nistiprint_shared.services.bom_service.bom_service') as bom, \
             patch('nistiprint_shared.services.estoque_command_service.estoque_command_service.execute_command',
                   return_value=result) as execute:
            bom.publish_effective_version.return_value = version
            with patch.object(stock, '_resolve_deposito', return_value=7), \
                 patch.object(stock, '_validate_stock_eligibility'), \
                 patch.object(stock, '_validate_sector_permission'):
                movement_id = stock.registrar_producao_com_insumos(1, '2', deposito_id=7)

        self.assertEqual(movement_id, '44')
        command = execute.call_args.args[0]
        self.assertEqual(command['command_type'], 'PRODUCAO_IMEDIATA')
        self.assertEqual([m['tipo_movimentacao'] for m in command['movimentos']],
                         ['ENTRADA', 'SAIDA_INSUMO_PRODUCAO'])
        self.assertEqual(command['movimentos'][1]['quantidade'], '-0.5')
        self.assertEqual(command['source']['bom_version_id'], 'version-1')
        self.assertTrue(execute.call_args.kwargs['allow_when_disabled'])

    def test_reconciliacao_fixa_a_versao_bom_no_item_antes_dos_efeitos(self):
        intencao = IntencaoItem({'id': 8, 'produto_id': 1, 'quantidade': 3})
        table = MagicMock()
        with patch.object(supabase_db, 'table', return_value=table):
            motor = MotorReconciliacaoEstoque()
        table.update.return_value.eq.return_value.is_.return_value.execute.return_value = SimpleNamespace(data=[])
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
            data=[{'bom_version_id': 'version-2'}]
        )
        candidate = {'id': 'version-2'}
        effective = {'id': 'version-2', 'graph': {'roots': [1], 'nodes': {}}}
        with patch.object(supabase_db, 'table', return_value=table), \
             patch('nistiprint_shared.services.motor_reconciliacao_estoque.bom_service.publish_effective_version',
                   return_value=candidate) as publish, \
             patch('nistiprint_shared.services.motor_reconciliacao_estoque.bom_service.get_version',
                   return_value=effective) as get_version:
            result = motor._get_or_pin_bom_version(8, intencao)

        publish.assert_called_once_with(1)
        table.update.assert_called_once_with({'bom_version_id': 'version-2'})
        get_version.assert_called_once_with('version-2')
        self.assertEqual(intencao.bom_version_id, 'version-2')
        self.assertEqual(result, effective)


if __name__ == '__main__':
    unittest.main()
