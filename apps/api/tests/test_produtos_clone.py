"""Contrato HTTP da clonagem de produtos."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, 'table', return_value=MagicMock()):
    import routes.produtos_api as produtos_api  # noqa: E402


class DatabaseError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class TestProdutosClone(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(produtos_api.produtos_api_bp)
        self.client = app.test_client()

    def test_clone_retorna_produto_e_id_para_redirecionamento(self):
        cloned = {'id': 901, 'sku': 'NOVO', 'status': 'rascunho'}
        with patch.object(produtos_api.product_service, 'clone_product', return_value=cloned) as clone:
            response = self.client.post('/api/v2/produtos/433/clone', json={
                'new_sku': ' NOVO ', 'new_name': 'Nova cópia',
            })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['product'], cloned)
        clone.assert_called_once_with('433', 'NOVO', 'Nova cópia', {})

    def test_clone_rejeita_dados_invalidos(self):
        with patch.object(produtos_api.product_service, 'clone_product') as clone:
            for payload in (None, {}, {'new_sku': ''}, {'new_sku': 'X' * 101}):
                response = self.client.post('/api/v2/produtos/433/clone', json=payload)
                self.assertEqual(response.status_code, 400)
            response = self.client.post('/api/v2/produtos/433/clone', json={
                'new_sku': 'NOVO', 'child_skus': {'10': '  '},
            })
            self.assertEqual(response.status_code, 400)
            clone.assert_not_called()

    def test_clone_retorna_404_para_origem_inexistente(self):
        with patch.object(produtos_api.product_service, 'clone_product', side_effect=DatabaseError('P0002', 'missing')):
            response = self.client.post('/api/v2/produtos/433/clone', json={'new_sku': 'NOVO'})
        self.assertEqual(response.status_code, 404)

    def test_clone_retorna_400_para_sku_repetido(self):
        with patch.object(produtos_api.product_service, 'clone_product', side_effect=DatabaseError('23505', 'duplicate')):
            response = self.client.post('/api/v2/produtos/433/clone', json={'new_sku': 'NOVO'})
        self.assertEqual(response.status_code, 400)

    def test_servico_usa_uma_rpc_para_familia_inteira(self):
        cloned = {'id': 901, 'sku': 'NOVO'}
        with patch.object(supabase_db, 'rpc', return_value=SimpleNamespace(execute=lambda: SimpleNamespace(data=cloned))) as rpc:
            result = produtos_api.product_service.clone_product('433', 'NOVO', None, {'12': 'NOVO-AZUL'})
        self.assertEqual(result, cloned)
        rpc.assert_called_once_with('clonar_produto_interno', {
            'p_produto_id': 433, 'p_novo_sku': 'NOVO', 'p_novo_nome': None,
            'p_child_skus': {'12': 'NOVO-AZUL'},
        })


if __name__ == '__main__':
    unittest.main()
