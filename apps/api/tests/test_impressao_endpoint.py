"""Contrato HTTP do endpoint de papeis de pedido."""

import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.impressao as impressao_module  # noqa: E402


def _order_data(order_id, _plataforma):
    return {
        'id': order_id,
        'numeroLoja': str(order_id),
        'itens': [],
        'total_items': 0,
        'hasCustomItem': 0,
        'plataforma_slug': 'shopee',
    }


class TestImpressaoEndpoint(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-secret')
        app.register_blueprint(impressao_module.impressao_api_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1

    def test_post_recebe_ids_no_corpo_json(self):
        resolution = {
            'ready': [{'pedido_id': 480920}, {'pedido_id': 481214}],
            'blocked': [],
        }
        with (
            patch.object(
                impressao_module.order_erp_reference_service,
                'resolve_many',
                return_value=resolution,
            ) as resolve_many,
            patch.object(
                impressao_module,
                '_build_order_print_data',
                side_effect=_order_data,
            ) as build_order,
        ):
            response = self.client.post(
                '/api/v2/pedidos/impressao',
                json={
                    'order_ids': [480920, 481214],
                    'plataforma': 'SHOPEE',
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['total'], 2)
        resolve_many.assert_called_once_with([480920, 481214], allow_remote=True)
        self.assertEqual(
            build_order.call_args_list,
            [call(480920, 'SHOPEE'), call(481214, 'SHOPEE')],
        )

    def test_post_sem_corpo_retorna_400(self):
        response = self.client.post('/api/v2/pedidos/impressao')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_post_com_lista_vazia_retorna_400(self):
        response = self.client.post(
            '/api/v2/pedidos/impressao',
            json={'order_ids': []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()['success'])

    def test_post_rejeita_ids_invalidos(self):
        invalid_values = ['abc', 1.5, True, 0, -1, None]
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                response = self.client.post(
                    '/api/v2/pedidos/impressao',
                    json={'order_ids': [invalid_value]},
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()['success'])

    def test_get_nao_e_mais_aceito(self):
        response = self.client.get(
            '/api/v2/pedidos/impressao?order_ids=480920,481214'
        )

        self.assertEqual(response.status_code, 405)


if __name__ == '__main__':
    unittest.main()
