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


if __name__ == '__main__':
    unittest.main()
