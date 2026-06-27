import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.order_erp_reference_service import OrderErpReferenceService


class _Query:
    def __init__(self, data):
        self.data = data
    def select(self, *args, **kwargs): return self
    def eq(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def update(self, *args, **kwargs): return self
    def execute(self): return SimpleNamespace(data=self.data)


class TestOrderErpReferenceService(unittest.TestCase):
    def test_existing_reference_is_returned_without_remote_lookup(self):
        service = OrderErpReferenceService()
        pedido = {
            'id': 10, 'erp_integration_id': 2, 'erp_store_id': 'shop',
            'erp_order_id': 99, 'erp_order_number': '1234',
        }
        with patch('nistiprint_shared.services.order_erp_reference_service.supabase_db.table', return_value=_Query([pedido])), \
             patch('nistiprint_shared.services.order_erp_reference_service.integration_capability_service.resolve') as resolve:
            result = service.resolve_order(10)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['erp_order_number'], '1234')
        resolve.assert_not_called()

    def test_ambiguous_link_blocks_only_the_order(self):
        service = OrderErpReferenceService()
        pedido = {
            'id': 10, 'marketplace_module_id': 'shopee',
            'marketplace_order_id': 'SN1', 'marketplace_integration_id': 12,
        }
        resolution = SimpleNamespace(reason='ambiguous_erp_link', responsible_integration=None)
        with patch('nistiprint_shared.services.order_erp_reference_service.supabase_db.table', return_value=_Query([pedido])), \
             patch('nistiprint_shared.services.order_erp_reference_service.integration_capability_service.resolve', return_value=resolution):
            result = service.resolve_order(10)
        self.assertEqual(result['status'], 'ambiguous')


if __name__ == '__main__':
    unittest.main()
