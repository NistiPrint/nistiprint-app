import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import canonical_order_status_service as status_service


class TestCanonicalOrderStatusService(unittest.TestCase):
    def test_shopee_default_status_mapping(self):
        service = status_service.CanonicalOrderStatusService()

        with patch.object(service, '_resolve_from_db', return_value=None):
            self.assertEqual(service.resolve_shopee('UNPAID').internal_situacao_pedido_id, 1)
            self.assertEqual(service.resolve_shopee('READY_TO_SHIP').internal_situacao_pedido_id, 2)
            self.assertEqual(service.resolve_shopee('PROCESSED').internal_situacao_pedido_id, 4)
            self.assertEqual(service.resolve_shopee('SHIPPED').internal_situacao_pedido_id, 5)
            self.assertEqual(service.resolve_shopee('COMPLETED').internal_situacao_pedido_id, 6)
            self.assertEqual(service.resolve_shopee('CANCELLED').internal_situacao_pedido_id, 7)

    def test_mercadolivre_shipping_precedence_over_payment(self):
        service = status_service.CanonicalOrderStatusService()

        with patch.object(service, '_resolve_from_db', return_value=None):
            resolved = service.resolve_mercadolivre(
                payment_status='approved',
                shipping_status='delivered',
            )

        self.assertEqual(resolved.internal_situacao_pedido_id, 6)
        self.assertEqual(resolved.status_domain, 'shipping')
        self.assertEqual(resolved.external_status_id, 'delivered')

    def test_mercadolivre_ready_to_ship_mapping(self):
        service = status_service.CanonicalOrderStatusService()

        with patch.object(service, '_resolve_from_db', return_value=None):
            resolved = service.resolve_mercadolivre(
                payment_status='approved',
                shipping_status='ready_to_ship',
            )

        self.assertEqual(resolved.internal_situacao_pedido_id, 4)
        self.assertEqual(resolved.status_domain, 'shipping')

    def test_mercadolivre_cancel_precedence(self):
        service = status_service.CanonicalOrderStatusService()

        with patch.object(service, '_resolve_from_db', return_value=None):
            resolved = service.resolve_mercadolivre(
                payment_status='refunded',
                shipping_status='delivered',
            )

        self.assertEqual(resolved.internal_situacao_pedido_id, 7)
        self.assertEqual(resolved.status_domain, 'payment')

    def test_db_mapping_wins_over_fallback(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.is_.return_value.execute.return_value.data = [
            {'internal_situacao_pedido_id': 3}
        ]

        with patch.object(status_service.supabase_db, 'table', return_value=table):
            resolved = status_service.CanonicalOrderStatusService().resolve_shopee('PROCESSED')

        self.assertEqual(resolved.internal_situacao_pedido_id, 3)
        self.assertEqual(resolved.source, 'db')


if __name__ == '__main__':
    unittest.main()
