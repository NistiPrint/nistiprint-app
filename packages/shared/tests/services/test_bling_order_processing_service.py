import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import bling_order_processing_service as bos


class TestBlingOrderProcessingServiceHelpers(unittest.TestCase):
    @patch('nistiprint_shared.services.bling.bling_client.BlingClient')
    def test_fetch_bling_order_detail_uses_bling_client(self, bling_client_cls):
        bling_client = MagicMock()
        bling_client.get_order.return_value = {'id': 123, 'contato': {'nome': 'Cliente'}}
        bling_client_cls.create_client_for_integration_id.return_value = bling_client

        detalhe = bos._fetch_bling_order_detail({'id': 77}, 123)

        self.assertEqual(detalhe, {'id': 123, 'contato': {'nome': 'Cliente'}})
        bling_client_cls.create_client_for_integration_id.assert_called_once_with(77)
        bling_client.get_order.assert_called_once_with(123)

    def test_process_webhook_fails_when_detail_is_missing(self):
        payload = {'id': 999, 'numero': '1', 'numeroLoja': 'ABC'}

        with patch.object(bos, '_resolve_bling_instance', return_value={'id': 12, 'config': {}}), \
             patch.object(bos, '_fetch_bling_order_detail', return_value=None):
            result = bos.process_webhook(payload)

        self.assertEqual(result['status'], 'error')
        self.assertIn('detalhe Bling indispon', result['message'])

    def test_resolve_shipping_carrier_uses_fresh_shopee_data(self):
        shopee_data = {
            'shipping_carrier': 'Entrega Rapida Shopee',
            'package_list': [
                {'shipping_carrier': 'Fallback Package'}
            ],
        }

        carrier = bos._resolve_shipping_carrier(shopee_data, '2511000001')

        self.assertEqual(carrier, 'Entrega Rapida Shopee')

    def test_resolve_shipping_carrier_falls_back_to_saved_row(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'shipping_carrier': None,
                'package_list': [
                    {'shipping_carrier': 'Entrega Rapida'}
                ],
            }
        ]

        with patch.object(bos.supabase_db, 'table', return_value=table):
            carrier = bos._resolve_shipping_carrier(None, '2511000002')

        self.assertEqual(carrier, 'Entrega Rapida')

    def test_detect_and_mark_personalized_calls_identifier(self):
        payload = {
            'numero': '12345',
            'numeroLoja': '2511000003',
            'loja': {'id': 204047801},
            'itens': [
                {'descricao': 'Agenda Personalizada', 'produto': {'id': 101}},
            ],
        }

        with patch(
            'nistiprint_shared.services.personalized_order_identifier.personalized_order_identifier.process_order',
            return_value={'success': True, 'personalized_items': [0]},
        ) as process_order:
            bos._detect_and_mark_personalized(payload, pedido_id=99)

        process_order.assert_called_once_with(payload)

    def test_upsert_pedido_master_does_not_overwrite_cliente_with_empty_json(self):
        payload = {
            'id': 1,
            'numero': '123',
            'numeroLoja': '456',
            'total': 10,
            'data': '2026-05-02',
            'situacao': {'id': 2},
            'contato': {},
            'itens': [],
        }

        table = MagicMock()
        table.upsert.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos.supabase_db, 'table', return_value=table), \
             patch.object(bos, '_resolve_situacao_interna', return_value=42), \
             patch.object(bos, '_upsert_itens_pedido'), \
             patch.object(bos.logger, 'info'):
            pedido_id = bos._upsert_pedido_master(
                payload,
                pedido_bling_id=11,
                pedido_shopee_id=None,
                bling_integration_id=22,
                marketplace_integration_id=None,
                canal_venda_id=None,
                is_flex=False,
                modalidade=None,
                shopee_data=None,
            )

        self.assertEqual(pedido_id, 321)
        upsert_data = table.upsert.call_args.args[0]
        self.assertNotIn('informacoes_cliente', upsert_data)


if __name__ == '__main__':
    unittest.main()
