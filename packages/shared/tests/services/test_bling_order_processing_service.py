import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import bling_order_processing_service as bos


class TestBlingOrderProcessingServiceHelpers(unittest.TestCase):
    def test_resolve_shipping_carrier_uses_fresh_shopee_data(self):
        shopee_data = {
            'shipping_carrier': 'Entrega Rápida Shopee',
            'package_list': [
                {'shipping_carrier': 'Fallback Package'}
            ],
        }

        carrier = bos._resolve_shipping_carrier(shopee_data, '2511000001')

        self.assertEqual(carrier, 'Entrega Rápida Shopee')

    def test_resolve_shipping_carrier_falls_back_to_saved_row(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'shipping_carrier': None,
                'package_list': [
                    {'shipping_carrier': 'Entrega Rápida'}
                ],
            }
        ]

        with patch.object(bos.supabase_db, 'table', return_value=table):
            carrier = bos._resolve_shipping_carrier(None, '2511000002')

        self.assertEqual(carrier, 'Entrega Rápida')

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


if __name__ == '__main__':
    unittest.main()
