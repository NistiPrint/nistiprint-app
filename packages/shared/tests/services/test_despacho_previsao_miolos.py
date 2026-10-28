import sys
import unittest
from pathlib import Path

SHARED_PATH = Path(__file__).resolve().parents[2]
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

from nistiprint_shared.services.despacho_previsao_miolos import build_previsao_miolos  # noqa: E402


def miolo(product_id, available, name=None):
    return {
        'id': product_id, 'name': name or f'Miolo {product_id}', 'sku': f'MIO-{product_id}',
        'stock_details': {'quantidade': available, 'quantidade_reservada': 0, 'quantidade_disponivel': available},
    }


def line(produto_id, quantidade, miolo_id=None, miolo_nome=None, **extra):
    return {
        'produto_id': produto_id, 'quantidade': quantidade, 'descricao': f'Produto {produto_id}',
        'id_produto_miolo': miolo_id, 'miolo_nome': miolo_nome, 'miolo_chave': miolo_nome, **extra,
    }


def lote(chave, linhas, marketplace='Shopee', modalidade='Normal', dia='2026-10-28', bucket='hoje', pedidos=3):
    return {
        'lote_chave': chave, 'integration_id': 1, 'nome_marketplace': marketplace,
        'nome_modalidade': modalidade, 'data_limite_dia': dia, 'bucket': bucket,
        'qtd_pedidos': pedidos, 'linhas': linhas,
    }


class PrevisaoMiolosTest(unittest.TestCase):
    def test_same_miolo_is_totalled_across_lotes_with_breakdown(self):
        result = build_previsao_miolos(
            [lote('a', [line(100, 6, 10, 'Miolo 10'), line(101, 2, 10, 'Miolo 10')]),
             lote('b', [line(100, 4, 10, 'Miolo 10')], marketplace='Mercado Livre', dia='2026-10-29', bucket='amanha')],
            [miolo(10, available=5)],
        )
        row = result['miolos'][0]
        self.assertEqual((row['quantidade_total'], row['estoque_disponivel'], row['falta']), (12, 5, 7))
        self.assertEqual([(p['nome_marketplace'], p['data_limite_dia'], p['quantidade']) for p in row['por_lote']],
                         [('Shopee', '2026-10-28', 8), ('Mercado Livre', '2026-10-29', 4)])
        self.assertEqual([item['total_miolos'] for item in result['lotes']], [8, 4])
        self.assertEqual(result['resumo']['total_pedidos'], 6)
        self.assertEqual((result['resumo']['total_miolos'], result['resumo']['total_falta']), (12, 7))

    def test_stock_larger_than_forecast_leaves_no_shortage(self):
        result = build_previsao_miolos([lote('a', [line(100, 3, 10, 'Miolo 10')])], [miolo(10, available=50)])
        self.assertEqual(result['miolos'][0]['falta'], 0)

    def test_bom_factor_matches_the_published_planning(self):
        graph = {'nodes': {'100': {'componentes': [{'componente_id': 10, 'quantidade_necessaria': 2}]}}}
        result = build_previsao_miolos(
            [lote('a', [line(100, 5, 10, 'Miolo 10')])], [miolo(10, available=4)], graph)
        self.assertEqual((result['miolos'][0]['quantidade_total'], result['miolos'][0]['falta']), (10, 6))

    def test_lines_without_miolo_are_reported_and_not_counted(self):
        result = build_previsao_miolos(
            [lote('a', [line(100, 3, 10, 'Miolo 10'), line(200, 4)])], [miolo(10, available=0)])
        self.assertEqual(result['resumo']['linhas_sem_miolo'], 1)
        self.assertEqual(result['resumo']['total_miolos'], 3)
        self.assertEqual(result['lotes'][0]['sem_miolo'][0]['quantidade'], 4)

    def test_circular_bom_does_not_break_the_forecast(self):
        graph = {'nodes': {'100': {'componentes': [{'componente_id': 101, 'quantidade_necessaria': 1}]},
                           '101': {'componentes': [{'componente_id': 100, 'quantidade_necessaria': 1}]}}}
        result = build_previsao_miolos([lote('a', [line(100, 2, 10, 'Miolo 10')])], [miolo(10, available=1)], graph)
        self.assertEqual(result['resumo']['linhas_sem_miolo'], 1)
        self.assertIn('circular', result['lotes'][0]['sem_miolo'][0]['motivo'])

    def test_miolo_without_stock_registry_has_unknown_stock_not_zero(self):
        result = build_previsao_miolos([lote('a', [line(100, 3, None, 'Miolo avulso')])], [])
        row = result['miolos'][0]
        self.assertIsNone(row['estoque_disponivel'])
        self.assertTrue(row['sem_estoque_cadastrado'])
        self.assertEqual(row['falta'], 3)

    def test_empty_input_is_a_valid_forecast(self):
        result = build_previsao_miolos([], [])
        self.assertEqual(result['lotes'], [])
        self.assertEqual(result['resumo']['total_lotes'], 0)


if __name__ == '__main__':
    unittest.main()
