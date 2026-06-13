import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import canonical_order_snapshot_service as snapshot_module


class TestCanonicalOrderSnapshotService(unittest.TestCase):
    def test_upsert_snapshot_creates_snapshot_updates_pedido_and_items(self):
        snapshots = MagicMock()
        snapshots.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        snapshots.insert.return_value.execute.return_value.data = [{'id': 1}]

        pedidos = MagicMock()
        pedidos.update.return_value.eq.return_value.execute.return_value.data = [{'id': 10}]

        itens = MagicMock()
        itens.delete.return_value.eq.return_value.execute.return_value.data = []
        itens.insert.return_value.execute.return_value.data = [{'id': 99}]

        def table_side_effect(name):
            if name == 'pedido_snapshots':
                return snapshots
            if name == 'pedidos':
                return pedidos
            if name == 'itens_pedido':
                return itens
            raise AssertionError(name)

        service = snapshot_module.CanonicalOrderSnapshotService()
        with patch.object(snapshot_module.supabase_db, 'table', side_effect=table_side_effect), \
             patch.object(snapshot_module, 'get_now_iso', return_value='2026-06-13T10:00:00-03:00'):
            result = service.upsert_snapshot(
                pedido_id=10,
                ingest_source='shopee',
                marketplace='shopee',
                marketplace_order_id='250613ABC',
                marketplace_integration_id=77,
                bling_integration_id=22,
                bling_order_id=123,
                bling_order_number='456',
                customer={'name': 'Maria', 'username': 'maria_shop'},
                items=[{'sku': 'SKU1', 'name': 'Produto', 'quantity': 2, 'unit_price': 12.5}],
                logistics={'shipping_carrier': 'Full', 'ship_by_date': '2026-06-14T12:00:00-03:00'},
                financial={'total': 25, 'currency': 'BRL'},
                platform_fields={'buyer_username': 'maria_shop'},
                upsert_items=True,
            )

        self.assertTrue(result['success'])
        inserted_snapshot = snapshots.insert.call_args.args[0]
        self.assertEqual(inserted_snapshot['identity']['marketplace_order_id'], '250613ABC')
        self.assertEqual(inserted_snapshot['customer']['username'], 'maria_shop')

        pedido_update = pedidos.update.call_args.args[0]
        self.assertEqual(pedido_update['marketplace_order_id'], '250613ABC')
        self.assertEqual(pedido_update['buyer_username'], 'maria_shop')
        self.assertEqual(pedido_update['bling_order_number'], '456')

        item_rows = itens.insert.call_args.args[0]
        self.assertEqual(item_rows[0]['sku_externo'], 'SKU1')
        self.assertEqual(item_rows[0]['subtotal'], 25.0)


if __name__ == '__main__':
    unittest.main()
