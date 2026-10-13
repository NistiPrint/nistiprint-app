import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from nistiprint_shared.services.inventory_service import InventoryService


class InventoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = InventoryService()
        self.service.db = Mock()

    def test_open_inventory_uses_atomic_snapshot_rpc(self):
        self.service.db.rpc.return_value.execute.return_value = SimpleNamespace(
            data={'sessao_id': 'session-1', 'items_count': 3, 'status': 'ABERTA'}
        )
        result = self.service.start_inventory(1, 7, [2, 3], 'cycle count')

        self.assertEqual(result['items_count'], 3)
        self.service.db.rpc.assert_called_once_with('abrir_sessao_inventario', {
            'p_deposito_id': 1, 'p_usuario_id': 7, 'p_produtos': [2, 3],
            'p_observacoes': 'cycle count',
        })

    def test_finalize_inventory_delegates_all_adjustments_and_close_to_one_rpc(self):
        expected = {'status': 'success', 'sessao_id': 'session-1', 'ajustes_realizados': 2}
        self.service.db.rpc.return_value.execute.return_value = SimpleNamespace(data=expected)

        result = self.service.finalize_inventory('session-1', 7)

        self.assertEqual(result, expected)
        self.service.db.rpc.assert_called_once_with('finalizar_sessao_inventario', {
            'p_sessao_id': 'session-1', 'p_usuario_id': 7,
        })


if __name__ == '__main__':
    unittest.main()
