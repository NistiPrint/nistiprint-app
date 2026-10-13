import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nistiprint_shared.services.estoque_outbox_service import EstoqueOutboxService


class Rpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class EstoqueOutboxServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.notifications = Mock()
        self.service = EstoqueOutboxService(self.db, self.notifications)
        self.db.rpc.side_effect = lambda name, args: Rpc(
            [{'id': 17, 'lease_token': 'lease-1', 'payload': {'operation_id': 'op-1'}}]
            if name == 'claim_estoque_eventos_outbox' else True
        )

    def test_publishes_only_to_authorized_recipients_then_acknowledges(self):
        with patch.object(self.service, 'authorized_user_ids', return_value=['8', '21']):
            result = self.service.process_batch(worker_id='worker-test')

        self.assertEqual(result, {'claimed': 1, 'delivered': 1, 'failed': 0})
        self.assertEqual(self.notifications.publish_user_event.call_count, 2)
        self.assertEqual(self.notifications.publish_user_event.call_args_list[0].args[0], '8')
        self.assertEqual(self.notifications.publish_user_event.call_args_list[1].args[0], '21')
        self.assertEqual(self.db.rpc.call_args.args[0], 'finish_estoque_evento_outbox')
        self.assertIsNone(self.db.rpc.call_args.args[1]['p_error'])

    def test_failed_publish_releases_event_with_retry_error(self):
        self.notifications.publish_user_event.return_value = False
        with patch.object(self.service, 'authorized_user_ids', return_value=['8']):
            result = self.service.process_batch(worker_id='worker-test')

        self.assertEqual(result, {'claimed': 1, 'delivered': 0, 'failed': 1})
        finish_calls = [call for call in self.db.rpc.call_args_list
                        if call.args[0] == 'finish_estoque_evento_outbox']
        self.assertEqual(len(finish_calls), 1)
        self.assertIn('Falha ao publicar', finish_calls[0].args[1]['p_error'])


if __name__ == '__main__':
    unittest.main()
