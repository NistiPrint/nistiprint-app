"""Batch BOM reads keep inferred groups separate from persisted classifications."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nistiprint_shared.models.bom import BOMItem  # noqa: E402
from nistiprint_shared.services.bom_lote_service import BomLoteService  # noqa: E402


class TestBomLoteService(unittest.TestCase):
    def test_consulta_inclui_colunas_sem_vinculo_e_preserva_grupo_raw(self):
        service = BomLoteService()
        recipient = {'id': 10, 'sku': 'INTER-10', 'nome': 'Intermediário', 'parent_id': None}
        component = {'id': 20, 'sku': 'MP-20', 'nome': 'Papel', 'unidade_medida': 'folha'}
        with patch.object(service, '_products', side_effect=[{10: recipient}, {20: component}]), \
             patch('nistiprint_shared.services.bom_lote_service.bom_service.get_bom_for_multiple_products',
                   return_value={10: [BOMItem(21, '2', is_inherited=True, group='MIOLO', line_id=101, produto_pai_id=9)]}), \
             patch('nistiprint_shared.services.bom_lote_service.supabase_db.table') as table:
            table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
                {'id': 101, 'grupo': None},
            ]
            result = service.consulta([10], [20])

        self.assertEqual(result['componentes'], [component])
        self.assertEqual(result['composicoes']['10'][0]['grupo'], 'MIOLO')
        self.assertIsNone(result['composicoes']['10'][0]['grupo_persistido'])
        self.assertTrue(result['composicoes']['10'][0]['is_inherited'])

    def test_apply_reuses_the_review_snapshot_without_reloading_live_state(self):
        service = BomLoteService()
        product = {'id': 10, 'sku': 'INTER-10', 'parent_id': None, 'herdar_bom_pai': False}
        compositions = {'10': [{'componente_id': 20, 'quantidade_necessaria': '2',
                                'unidade_medida': 'un', 'is_inherited': False,
                                'grupo': None, 'grupo_persistido': None, 'line_id': 101,
                                'produto_pai_id': 10}]}
        products = [product]
        tokens = {'10': service._token(product, compositions['10'])}
        operations = [{'produto_id': 10, 'componente_id': 20, 'acao': 'definir', 'quantidade': '3'}]
        review = service._preview_snapshot([10], operations, tokens, compositions, products)
        with patch('nistiprint_shared.services.bom_lote_service.supabase_db.rpc',
                   return_value=SimpleNamespace(execute=lambda: SimpleNamespace(data={'lote_id': 'batch-1'}))) as rpc:
            first = service.aplicar([10], operations, tokens, review['revisao'], 'idempotency-key-001', 7,
                                    compositions, products)
            second = service.aplicar([10], operations, tokens, review['revisao'], 'idempotency-key-001', 7,
                                     compositions, products)

        self.assertEqual(first, {'lote_id': 'batch-1'})
        self.assertEqual(second, first)
        self.assertEqual(rpc.call_count, 2)
        self.assertEqual(rpc.call_args.args[1]['p_expected_composicoes'], compositions)


if __name__ == '__main__':
    unittest.main()
