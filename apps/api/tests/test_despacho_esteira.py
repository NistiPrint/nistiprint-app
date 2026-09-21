"""Contrato HTTP da esteira de pedidos com prazo relativo."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.despacho as despacho_module  # noqa: E402


class TestDespachoEsteiraEndpoint(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-secret')
        app.register_blueprint(
            despacho_module.despacho_bp,
            url_prefix='/api/v2/despacho',
        )
        self.client = app.test_client()

    def test_retorna_contrato_canonico_da_rpc(self):
        pedidos = [{
            'pedido_id': 489700,
            'numero_pedido': '489700',
            'marketplace_nome': 'Shopee',
            'compromisso_em': '2026-09-21T15:40:00+00:00',
            'em_rascunho': False,
        }]
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data=pedidos)

        with (
            patch.object(despacho_module, 'get_current_user', return_value={'id': 1}),
            patch.object(despacho_module, 'supabase_db', banco),
        ):
            response = self.client.get('/api/v2/despacho/esteira')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            'success': True,
            'data': {'pedidos': pedidos},
        })
        banco.rpc.assert_called_once_with('despacho_esteira_relativo')

    def test_normaliza_retorno_nulo_da_rpc_como_fila_vazia(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.return_value = SimpleNamespace(data=None)

        with (
            patch.object(despacho_module, 'get_current_user', return_value={'id': 1}),
            patch.object(despacho_module, 'supabase_db', banco),
        ):
            response = self.client.get('/api/v2/despacho/esteira')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['data']['pedidos'], [])

    def test_exige_usuario_autenticado(self):
        banco = MagicMock()

        with (
            patch.object(despacho_module, 'get_current_user', return_value=None),
            patch.object(despacho_module, 'supabase_db', banco),
        ):
            response = self.client.get('/api/v2/despacho/esteira')

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['success'])
        banco.rpc.assert_not_called()

    def test_retorna_500_quando_a_rpc_falha(self):
        banco = MagicMock()
        banco.rpc.return_value.execute.side_effect = RuntimeError('falha da fila')

        with (
            patch.object(despacho_module, 'get_current_user', return_value={'id': 1}),
            patch.object(despacho_module, 'supabase_db', banco),
        ):
            response = self.client.get('/api/v2/despacho/esteira')

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
