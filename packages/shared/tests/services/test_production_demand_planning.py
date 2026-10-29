import sys
import unittest
from pathlib import Path

SHARED_PATH = Path(__file__).resolve().parents[2]
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

from nistiprint_shared.services.production_demand_planning import build_production_demand_plan, prepare_component_distributions  # noqa: E402


def product(product_id, available, minimum=0, reserved=0):
    return {
        'id': product_id, 'name': f'Produto {product_id}', 'sku': f'SKU-{product_id}',
        'stock_min': minimum,
        'stock_details': {
            'quantidade': available + reserved,
            'quantidade_reservada': reserved,
            'quantidade_disponivel': available,
        },
    }


def demand(demand_id, priority, date):
    return {'id': demand_id, 'nome': f'Demanda {demand_id}', 'prioridade_manual': priority, 'data_entrega': date}


def item(item_id, product_id, total, **progress):
    return {'id': item_id, 'produto_id': product_id, 'quantidade_total': total, **progress}


def graph(*lines):
    return {'nodes': {'100': {'componentes': [
        {'componente_id': product_id, 'quantidade_necessaria': factor} for product_id, factor in lines
    ]}}}


class ProductionDemandPlanningTest(unittest.TestCase):
    def test_shared_available_stock_covers_priority_then_deadline(self):
        result = build_production_demand_plan(
            'miolo', [product(10, available=7, minimum=3, reserved=2)],
            [demand(1, 0, '2026-10-27'), demand(2, 100, '2026-10-29')],
            {'1': [item(11, 100, 6, miolos_prontos_retirada_qtd=1)],
             '2': [item(12, 100, 6, miolos_prontos_retirada_qtd=0)]},
            graph((10, 1)),
        )
        row = result['products'][0]
        self.assertEqual((row['estoque_fisico'], row['estoque_reservado'], row['estoque_disponivel']), (9, 2, 7))
        self.assertEqual((row['demanda_pendente'], row['coberto_estoque'], row['falta_demandas'], row['reposicao_minimo']), (11, 7, 4, 3))
        self.assertEqual([(d['demanda_id'], d['coberto_estoque'], d['falta_apos_estoque']) for d in row['demandas']],
                         [(2, 6, 0), (1, 1, 4)])

    def test_cover_stages_and_bom_factor_are_independent(self):
        products = [product(20, 1), product(21, 2)]
        demands = [demand(1, 0, '2026-10-27')]
        items = {'1': [item(11, 100, 5, capas_impressas_qtd=2, capas_produzidas_qtd=1)]}
        bom = graph((20, 2), (21, 1))
        printed = build_production_demand_plan('capa', [products[0]], demands, items, bom)['products'][0]
        finished = build_production_demand_plan('capa_acabada', [products[1]], demands, items, bom)['products'][0]
        self.assertEqual((printed['demanda_pendente'], printed['falta_demandas']), (6, 5))
        self.assertEqual((finished['demanda_pendente'], finished['falta_demandas']), (4, 2))

    def test_missing_mapping_is_signaled_and_not_counted(self):
        result = build_production_demand_plan('capa', [product(20, 0)],
            [demand(1, 0, '2026-10-27')], {'1': [item(11, 100, 3)]}, {'nodes': {'100': {'componentes': []}}})
        self.assertEqual(result['products'][0]['demanda_pendente'], 0)
        self.assertEqual(result['unmapped'][0]['item_id'], 11)

    def test_conflicting_miolo_mapping_is_signaled(self):
        result = build_production_demand_plan('miolo', [product(10, 0)],
            [demand(1, 0, '2026-10-27')],
            {'1': [{**item(11, 100, 3), 'id_produto_miolo': 99}]}, graph((10, 1)))
        self.assertEqual(result['products'][0]['demanda_pendente'], 0)
        self.assertIn('diverge', result['unmapped'][0]['motivo'])
        self.assertEqual(result['unmapped'][0]['pendente'], 3)

    def test_unmapped_simulation_miolos_keep_display_code_and_pending_units(self):
        items = [
            {**item(1, None, 5), 'miolo_nome': 'VACMNA', 'sku': 'VACMNA_FLR_BRR'},
            {**item(2, None, 1), 'miolo_nome': 'Miolo VACMNA', 'sku': 'VACMNA_JAEN1_BBB'},
            {**item(3, None, 1, miolos_prontos_retirada_qtd=1),
             'miolo_name': 'VACMNA', 'sku': 'VACMNA_JAEN2_BBB'},
            {**item(4, None, 4), 'miolo_nome': 'VACMNO', 'sku': 'VACMNO_MCP1_BBB'},
            {**item(5, None, 1), 'miolo_nome': 'VACMNO', 'sku': 'VACMNO_BLUE_PBP'},
            {**item(6, None, 1), 'miolo_nome': 'VACMNO', 'sku': 'VACMNO_MCP2_BBB'},
            {**item(7, None, 1), 'miolo_nome': 'VACMNO', 'sku': 'VACMNO_MCP3_BBB'},
            {**item(8, None, 1), 'miolo_nome': 'VACMNA', 'sku': 'VACMNA_JAEN3_RBB'},
            {**item(9, None, 1), 'miolo_nome': 'VACMNA', 'sku': 'VACMNA_JDF3_BRR'},
            {**item(10, None, 1), 'miolo_nome': 'VACMNA', 'sku': 'VACMNA_LILAS_BBB'},
            {**item(11, None, 5, miolos_prontos_retirada_qtd=2),
             'miolo_nome': 'PARCIAL', 'sku': 'PARCIAL-1'},
            {**item(12, None, 1), 'miolo_nome': 'VACMNA', 'sku': 'VACMNA_EXTRA'},
        ]
        result = build_production_demand_plan(
            'miolo', [product(56, 20), product(88, 10)],
            [{**demand('sim', 0, '2026-10-27'), 'simulacao': True}],
            {'sim': items}, {'nodes': {}},
        )

        self.assertEqual([row['demanda_pendente'] for row in result['products']], [0, 0])
        self.assertEqual(len(result['unmapped']), 11)
        vacmna = sum(row['pendente'] for row in result['unmapped']
                     if row['miolo_nome'].replace('Miolo ', '') == 'VACMNA')
        vacmno = sum(row['pendente'] for row in result['unmapped']
                     if row['miolo_nome'] == 'VACMNO')
        parcial = next(row['pendente'] for row in result['unmapped'] if row['miolo_nome'] == 'PARCIAL')
        self.assertEqual((vacmna, vacmno, parcial), (10, 7, 3))

    def test_unmapped_miolo_name_uses_torre_sku_slice_and_corrections(self):
        result = build_production_demand_plan(
            'miolo', [product(56, 0)], [demand(1, 0, '2026-10-27')],
            {'1': [{**item(12, None, 2), 'sku': 'CADMNA_JAEN3_RBB'}]},
            {'nodes': {}},
        )
        self.assertEqual(result['unmapped'][0]['miolo_nome'], 'VACMNA')

    def test_multiple_products_in_one_stage_are_ambiguous(self):
        result = build_production_demand_plan('capa', [product(20, 0), product(21, 0)],
            [demand(1, 0, '2026-10-27')], {'1': [item(11, 100, 3)]},
            graph((20, 1), (21, 1)))
        self.assertEqual(sum(row['demanda_pendente'] for row in result['products']), 0)
        self.assertIn('Mais de um produto', result['unmapped'][0]['motivo'])

    def test_inactive_component_is_not_silently_ignored(self):
        result = build_production_demand_plan('capa', [product(20, 0)],
            [demand(1, 0, '2026-10-27')], {'1': [item(11, 100, 3)]},
            graph((21, 1)), stage_product_ids=[20, 21])
        self.assertEqual(result['products'][0]['demanda_pendente'], 0)
        self.assertIn('inativo', result['unmapped'][0]['motivo'])

    def test_minimum_replenishment_uses_remaining_stock(self):
        result = build_production_demand_plan('miolo', [product(10, 10, minimum=5)],
            [demand(1, 0, '2026-10-27')], {'1': [item(11, 100, 7)]}, graph((10, 1)))
        row = result['products'][0]
        self.assertEqual(row['falta_demandas'], 0)
        self.assertEqual(row['reposicao_minimo'], 2)

    def test_allocation_converts_component_units_into_item_progress(self):
        items = {'11': item(11, 100, 5, capas_impressas_qtd=2)}
        prepared = prepare_component_distributions(20, 'CAPA_IMPRESSAO',
            [{'item_id': 11, 'quantidade': 4}], items, graph((20, 2)))
        self.assertEqual(prepared[0]['quantidade'], 4)
        self.assertEqual(prepared[0]['quantidade_estagio'], 2)
        with self.assertRaisesRegex(ValueError, 'não está vinculado'):
            prepare_component_distributions(20, 'CAPA_IMPRESSAO',
                [{'item_id': 11, 'quantidade': 4}], items, graph((21, 2)))


if __name__ == '__main__':
    unittest.main()
