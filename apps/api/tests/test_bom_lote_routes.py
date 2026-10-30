"""Contrato HTTP das rotas de composição em lote."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, 'table', return_value=MagicMock()):
    import routes.produtos_api as produtos_api  # noqa: E402
    import routes.produtos_base as produtos_base  # noqa: E402


class TestBomLoteRoutes(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(produtos_api.produtos_api_bp)
        self.client = app.test_client()
        self.permission_patch = patch.object(produtos_base, 'require_request_permission', return_value=None)
        self.permission_patch.start()

    def tearDown(self):
        self.permission_patch.stop()

    def test_candidates_forward_filters_and_pagination(self):
        products = [
            {'id': 4, 'papel_catalogo': 'individual', 'tipo_material': 'intermediario'},
            {'id': 5, 'papel_catalogo': 'modelo', 'tipo_material': 'intermediario'},
            {'id': 6, 'papel_catalogo': 'individual', 'tipo_material': 'servico'},
            {'id': 7, 'papel_catalogo': 'individual', 'tipo_material': 'intermediario', 'has_variants': True},
        ]
        with patch.object(produtos_api.product_service, 'get_products', return_value=(products, 3)) as query:
            response = self.client.get('/api/v2/produtos/bom/lote/candidatos?q=PAPEL&category_id=8&tipo_material=materia_prima&page=2&per_page=25')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p['id'] for p in response.get_json()['produtos']], [4])
        query.assert_called_once_with(q='PAPEL', categoria_id='8', material_type='materia_prima', page=2, per_page=25, include_variants=True, enrich=False)

    def test_consulta_encaminha_ids_selecionados(self):
        with patch('nistiprint_shared.services.bom_lote_service.bom_lote_service.consulta', return_value={'tokens': {'4': 'abc'}}) as consulta:
            response = self.client.post('/api/v2/produtos/bom/lote/consulta', json={'produto_ids': [4]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['tokens'], {'4': 'abc'})
        consulta.assert_called_once_with([4], [])

    def test_previa_conflict_returns_409(self):
        with patch('nistiprint_shared.services.bom_lote_service.bom_lote_service.previa', side_effect=RuntimeError('BOM_CONFLICT')):
            response = self.client.post('/api/v2/produtos/bom/lote/previa', json={
                'produto_ids': [4], 'operacoes': [], 'tokens': {'4': 'stale'},
            })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'BOM_CONFLICT')

    def test_apply_passes_actor_and_review_token(self):
        with patch.object(produtos_api, 'get_current_user', return_value={'id': 17}), \
             patch('nistiprint_shared.services.bom_lote_service.bom_lote_service.aplicar', return_value={'lote_id': 'batch-1'}) as apply:
            response = self.client.post('/api/v2/produtos/bom/lote/aplicar', json={
                'produto_ids': [4], 'operacoes': [{'produto_id': 4, 'componente_id': 9, 'acao': 'remover'}],
                'tokens': {'4': 'snapshot'}, 'revisao': 'review', 'idempotency_key': '1234567890123456',
                'composicoes_anteriores': {'4': []}, 'produtos_esperados': [{'id': 4}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['resultado'], {'lote_id': 'batch-1'})
        apply.assert_called_once_with(
            [4], [{'produto_id': 4, 'componente_id': 9, 'acao': 'remover'}],
            {'4': 'snapshot'}, 'review', '1234567890123456', 17,
            {'4': []}, [{'id': 4}],
        )


if __name__ == '__main__':
    unittest.main()
