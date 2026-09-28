"""Avaliação informativa da prontidão sem alterar a disponibilidade comercial."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, 'table'):
    import routes.produtos_api as produtos_api  # noqa: E402


class TestProductReadiness(unittest.TestCase):
    def setUp(self):
        self.service = produtos_api.product_service

    def assess(self, product_id, result):
        rpc = SimpleNamespace(execute=lambda: SimpleNamespace(data=result))
        with patch.object(supabase_db, 'rpc', return_value=rpc) as call:
            payload = self.service.evaluate_readiness(str(product_id))
        call.assert_called_once_with('produto_dominio_prontidao', {'p_produto_id': product_id})
        return payload

    def test_sql_readiness_returns_stable_codes_and_nonblocking_channel_notice(self):
        result = self.assess(1, {'ready': False, 'role': 'individual', 'structure': 'sem_ficha',
            'status': 'RASCUNHO', 'issues': [
                {'code': 'SKU_REQUIRED', 'message': 'Informe o SKU.', 'blocking': True},
                {'code': 'NAME_REQUIRED', 'message': 'Informe o nome do produto.', 'blocking': True},
                {'code': 'CATEGORY_REQUIRED', 'message': 'Classifique o produto em uma categoria.', 'blocking': True},
                {'code': 'UNIT_REQUIRED', 'message': 'Informe a unidade de medida.', 'blocking': True},
                {'code': 'CLASSIFICATION_REQUIRED', 'message': 'Informe a classificação do produto.', 'blocking': True},
                {'code': 'CHANNEL_LINK_MISSING', 'message': 'Vínculo com canal ainda não informado.', 'blocking': False},
            ]})
        codes = {issue['code'] for issue in result['issues']}
        self.assertEqual(result['status'], 'RASCUNHO')
        self.assertFalse(result['ready'])
        self.assertTrue({'SKU_REQUIRED', 'NAME_REQUIRED', 'CATEGORY_REQUIRED', 'UNIT_REQUIRED',
                         'CLASSIFICATION_REQUIRED', 'CHANNEL_LINK_MISSING'} <= codes)
        self.assertFalse(next(i for i in result['issues'] if i['code'] == 'CHANNEL_LINK_MISSING')['blocking'])

    def test_sql_readiness_reports_missing_bom(self):
        result = self.assess(2, {'ready': False, 'role': 'individual', 'structure': 'manufaturado',
            'status': 'EM_PREPARO', 'issues': [{'code': 'BOM_REQUIRED',
                'message': 'Inclua ao menos um componente válido na ficha técnica.', 'blocking': True}]})
        self.assertIn('BOM_REQUIRED', {issue['code'] for issue in result['issues']})

    def test_sql_readiness_does_not_change_commercial_status(self):
        product = {'status': 'ativo'}
        result = self.assess(3, {'ready': True, 'role': 'individual', 'structure': 'sem_ficha',
            'status': 'PRONTO', 'issues': []})
        self.assertTrue(result['ready'])
        self.assertEqual(result['status'], 'PRONTO')
        self.assertEqual(product['status'], 'ativo')

    def test_sql_readiness_reports_incomplete_variation_attributes(self):
        result = self.assess(5, {'ready': False, 'role': 'variacao', 'structure': 'sem_ficha',
            'status': 'EM_PREPARO', 'issues': [{'code': 'VARIATION_ATTRIBUTES_INCOMPLETE',
                'message': 'Preencha todos os atributos da combinação da variação.', 'blocking': True}]})
        self.assertIn('VARIATION_ATTRIBUTES_INCOMPLETE', {issue['code'] for issue in result['issues']})

    def test_novo_cadastro_comeca_em_rascunho(self):
        app = Flask(__name__)
        app.register_blueprint(produtos_api.produtos_api_bp)
        with patch.object(produtos_api.product_service, 'create', return_value={'id': 7, 'nome': 'Novo'}) as create:
            response = app.test_client().post('/api/v2/produtos', json={'sku': 'NOVO', 'name': 'Novo'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(create.call_args.args[0]['status'], 'rascunho')

    def test_grade_rejeita_variacao_sem_sku_informado(self):
        with self.assertRaisesRegex(ValueError, 'Informe o SKU da variação'):
            self.service.create_variant('4', {'sku': '  '})


if __name__ == '__main__':
    unittest.main()
