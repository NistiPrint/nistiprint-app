import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import marketplace_lifecycle_tasks as tasks


class TestMarketplaceLifecycleTasks(unittest.TestCase):
    def test_process_pending_effects_calls_transactional_rpc(self):
        table = MagicMock()
        table.select.return_value = table
        table.eq.return_value = table
        table.order.return_value = table
        table.limit.return_value = table
        table.execute.return_value.data = [{'id': 10}]
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = {
            'effect_id': 10,
            'status': 'processed',
            'alerts': 1,
        }

        with patch.object(tasks.supabase_db, 'table', return_value=table), \
             patch.object(tasks.supabase_db, 'rpc', return_value=rpc_query) as rpc:
            result = tasks.process_pending_effects()

        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['failed'], 0)
        rpc.assert_called_once_with(
            'process_marketplace_order_effect',
            {'p_effect_id': 10},
        )


if __name__ == '__main__':
    unittest.main()
