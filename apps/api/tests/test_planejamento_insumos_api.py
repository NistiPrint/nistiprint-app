import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
for path in (REPO_ROOT / 'apps' / 'api', REPO_ROOT / 'packages' / 'shared'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

with patch('nistiprint_shared.database.supabase_db_service.supabase_db.table', return_value=MagicMock()):
    import routes.demanda_producao_api as module  # noqa: E402


class PlanejamentoInsumosApiTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_invalid_stage_returns_400(self):
        with self.app.test_request_context('/planejamento-insumos?tipo=outro'):
            response, status = module.api_get_planejamento_insumos()
        self.assertEqual(status, 400)
        self.assertFalse(response.get_json()['success'])

    def test_planning_url_resolves_before_demand_id(self):
        self.app.register_blueprint(module.demanda_producao_api_bp)
        adapter = self.app.url_map.bind('localhost')
        endpoint, values = adapter.match('/api/v2/demanda_producao/planejamento-insumos', method='GET')
        self.assertEqual(endpoint, 'demanda_producao_api.api_get_planejamento_insumos')
        self.assertEqual(values, {})

    def test_returns_stock_and_demand_projection(self):
        products = [{'id': 10, 'name': 'Miolo A', 'sku': 'M10', 'status': 'ativo', 'stock_min': 3}]
        demands = [{'id': 1, 'nome': 'Demanda A', 'prioridade_manual': 10, 'data_entrega': '2026-10-27'}]
        items = {'1': [{'id': 11, 'produto_id': 100, 'quantidade_total': 8, 'miolos_prontos_retirada_qtd': 1}]}
        graph = {'nodes': {'100': {'componentes': [{'componente_id': 10, 'quantidade_necessaria': 1}]}}}
        stock = {'10': {'quantidade': 6, 'quantidade_reservada': 2, 'quantidade_disponivel': 4}}
        with self.app.test_request_context('/planejamento-insumos?tipo=miolo'), \
             patch.object(module.app_config_service, 'get_config', side_effect=lambda key: '6' if key == 'producao_miolos_category_id' else 'principal'), \
             patch.object(module.product_service, 'get_products', return_value=(products, 1)), \
             patch.object(module.estoque_service, 'get_saldos_em_lote', return_value=stock), \
             patch.object(module.demanda_producao_service, 'get_demandas_by_status', return_value=demands), \
             patch.object(module.demanda_producao_service, 'get_items_for_multiple_demandas', return_value=items), \
             patch.object(module.bom_service, 'load_effective_graph', return_value=graph):
            response = module.api_get_planejamento_insumos()
        body = response.get_json()
        self.assertTrue(body['success'])
        row = body['products'][0]
        self.assertEqual((row['estoque_disponivel'], row['demanda_pendente'], row['falta_demandas'], row['reposicao_minimo']), (4, 7, 3, 3))
        self.assertEqual(row['demandas'][0]['coberto_estoque'], 4)

    def test_component_reservation_updates_item_progress_in_item_units(self):
        service = module.demanda_producao_service._items
        existing = {'id': 11, 'demanda_id': 1, 'produto_id': 100, 'quantidade': 5, 'capas_impressas_qtd': 1}
        with patch.object(service, 'get_item_by_id', return_value=existing), \
             patch.object(service, '_persistir_intencao_eventos', return_value=existing) as persist, \
             patch.object(module.product_service, 'identify_product_role', return_value='CAPA_IMPRESSAO'), \
             patch('nistiprint_shared.services.demanda.items.auditoria_service.log_event'):
            service.registrar_saida_item_distribuida(
                [{'item_id': 11, 'quantidade': 4, 'quantidade_estagio': 2}], 20)
        self.assertEqual(persist.call_args.args[1]['capas_impressas_qtd'], 3)
        self.assertEqual(persist.call_args.args[2][0]['quantidade_reportada'], 2)


if __name__ == '__main__':
    unittest.main()
