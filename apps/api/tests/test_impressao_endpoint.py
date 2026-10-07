"""Contrato HTTP do endpoint de papeis de pedido."""

import sys
import unittest
import importlib
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

        class Query:
            def select(self, *_args): return self
            def in_(self, *_args): return self
            def execute(self): return type('Result', (), {'data': []})()

        banco = type('Database', (), {'table': lambda _self, _name: Query()})()
        with (
            patch.object(impressao_module, 'supabase_db', banco),
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

    def test_mercadolivre_gera_papel_sem_consultar_o_erp(self):
        class Query:
            def select(self, *_args):
                return self

            def in_(self, *_args):
                return self

            def execute(self):
                return type('Result', (), {'data': [{'id': 77, 'marketplace_module_id': 'mercadolivre'}]})()

        banco = type('Database', (), {'table': lambda _self, _name: Query()})()
        with (
            patch.object(impressao_module, 'supabase_db', banco),
            patch.object(impressao_module.order_erp_reference_service, 'resolve_many') as resolve_many,
            patch.object(impressao_module, '_build_orders_print_data_mercadolivre', return_value={
                'orders': [_order_data(77, None)], 'blocked_orders': [],
            }) as build_orders,
        ):
            response = self.client.post('/api/v2/pedidos/impressao', json={'order_ids': [77]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['data']['total'], 1)
        resolve_many.assert_not_called()
        build_orders.assert_called_once()

    def test_mercadolivre_carrega_itens_e_snapshots_em_lote(self):
        class Query:
            def __init__(self, table_name, calls):
                self.table_name = table_name
                self.calls = calls
            def select(self, *_args): return self
            def in_(self, field, values):
                self.calls.append((self.table_name, field, list(values)))
                return self
            def execute(self): return type('Result', (), {'data': []})()

        calls = []
        banco = type('Database', (), {
            'table': lambda _self, name: Query(name, calls),
        })()
        pedidos = [{
            'id': pedido_id, 'marketplace_module_id': 'mercadolivre',
            'marketplace_order_id': str(900000 + pedido_id),
            'marketplace_integration_id': 4,
        } for pedido_id in range(100, 125)]
        with (
            patch.object(impressao_module, 'supabase_db', banco),
            patch('nistiprint_shared.services.order_erp_reference_service._ml_pack_ids_por_pedido', return_value={}),
            patch('nistiprint_shared.services.mercadolivre_personalization_service.printable_personalizations_many',
                  return_value={pedido['id']: {'ready': True, 'by_item_id': {}} for pedido in pedidos}),
            patch.object(impressao_module, '_build_order_print_data', side_effect=lambda pedido_id, _filter, prepared: {
                **_order_data(pedido_id, None), 'plataforma_slug': 'mercadolivre',
            }),
        ):
            resultado = impressao_module._build_orders_print_data_mercadolivre(pedidos)

        self.assertEqual(len(resultado['orders']), 25)
        self.assertEqual(calls, [
            ('itens_pedido', 'pedido_id', list(range(100, 125))),
            ('pedido_snapshots', 'pedido_id', list(range(100, 125))),
        ])

    def test_avaliador_em_lote_preserva_personalizacao_aprovada_e_estado_pendente(self):
        service = importlib.import_module(
            'nistiprint_shared.services.mercadolivre_personalization_service'
        )
        sem_personalizacao = service.printable_personalizations_many(
            [{'id': 79}], {79: []},
        )
        self.assertTrue(sem_personalizacao[79]['ready'])
        items = [{'id': 501, 'quantidade': 1, 'personalizado': True}]
        stored = [{
            'id': 1, 'marketplace_integration_id': 4, 'pedido_id': 78,
            'item_pedido_id': 501, 'pack_id': 'pack-1', 'status': 'SUCCESS',
            'source': 'ai', 'context_hash': 'ctx-1', 'provider_message_id': 'msg-1',
            'quantity_to_personalize': 1, 'customization_name': 'Ana',
            'customization_initial': 'A', 'updated_at': '2026-10-07T10:00:00Z',
            'details': {'initial_source_message_id': 'msg-1'},
        }]
        conversations = {'pack-1': {'context_hash': 'ctx-1'}}
        messages = {'pack-1': [{'provider_message_id': 'msg-1', 'sender_role': 'buyer'}]}

        aprovado = service._evaluate_printable_personalizations(
            4, items, stored, conversations, messages, False,
        )
        pendente = service._evaluate_printable_personalizations(
            4, items, stored, conversations, messages, True,
        )

        self.assertTrue(aprovado['ready'])
        self.assertEqual(aprovado['by_item_id'][501][0]['customization_name'], 'Ana')
        self.assertFalse(pendente['ready'])
        self.assertEqual(pendente['by_item_id'][501][0]['customization_initial'], 'A')
        pedido = {
            'id': 78, 'marketplace_module_id': 'mercadolivre',
            'marketplace_order_id': '900078', 'marketplace_integration_id': 4,
            'informacoes_cliente': {},
        }
        papel = impressao_module._build_order_print_data(78, prepared={
            'pedido': pedido,
            'itens': [{
                'id': 501, 'pedido_id': 78, 'personalizado': True,
                'descricao': 'Capa personalizada', 'quantidade': 1,
                'preco_unitario': 10,
            }],
            'snapshot': {}, 'pack_id': None, 'personalizacao': pendente,
        })
        self.assertEqual(papel['itens'][0]['personalizations'], [])

    def test_personalizacoes_ml_fazem_consultas_por_lote_e_conta(self):
        service = importlib.import_module(
            'nistiprint_shared.services.mercadolivre_personalization_service'
        )

        class Query:
            def __init__(self, table_name, calls):
                self.table_name = table_name
                self.calls = calls
            def select(self, *_args, **_kwargs): return self
            def in_(self, *_args): return self
            def eq(self, *_args): return self
            def limit(self, *_args): return self
            def execute(self): return type('Result', (), {'data': []})()

        calls = []
        banco = type('Database', (), {
            'table': lambda _self, name: (calls.append(name) or Query(name, calls)),
        })()
        orders = [{
            'id': pedido_id, 'marketplace_integration_id': 4,
        } for pedido_id in range(200, 225)]
        items_by_order = {
            pedido['id']: [{'id': pedido['id'] + 1000, 'quantidade': 1, 'personalizado': True}]
            for pedido in orders
        }
        with (
            patch.object(service, 'supabase_db', banco),
            patch.object(service, '_integration', return_value={}),
        ):
            resultado = service.printable_personalizations_many(orders, items_by_order)

        self.assertEqual(len(resultado), 25)
        self.assertTrue(all(not order['ready'] for order in resultado.values()))
        self.assertEqual(calls, ['mercadolivre_personalizations', 'mercadolivre_chat_inbox'])

    def test_pedido_ml_com_classificacao_legada_usa_dados_locais_se_erp_bloquear(self):
        class Query:
            def select(self, *_args): return self
            def in_(self, *_args): return self
            def execute(self):
                return type('Result', (), {'data': [{'id': 78, 'marketplace_module_id': 'bling', 'origem': 'bling'}]})()

        banco = type('Database', (), {'table': lambda _self, _name: Query()})()
        ml_order = _order_data(78, None)
        ml_order['plataforma_slug'] = 'mercadolivre'
        resolution = {'ready': [], 'blocked': [{'pedido_id': 78, 'status': 'missing_erp_reference'}]}
        with (
            patch.object(impressao_module, 'supabase_db', banco),
            patch.object(impressao_module.order_erp_reference_service, 'resolve_many', return_value=resolution),
            patch.object(impressao_module, '_build_order_print_data', return_value=ml_order) as build_order,
        ):
            response = self.client.post('/api/v2/pedidos/impressao', json={'order_ids': [78]})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()['data']
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['orders'][0]['id'], 78)
        self.assertEqual(payload['blocked_total'], 0)
        build_order.assert_called_once_with(78, None)

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
