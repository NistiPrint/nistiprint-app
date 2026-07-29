import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import ai_personalization_service as service


class TestAiPersonalizationService(unittest.TestCase):
    def test_should_process_order_without_buyer_signal(self):
        self.assertFalse(
            service.should_process_order({
                "message_to_seller": "",
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_on_first_run_with_chat_only(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "",
                "has_chat_messages": True,
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_on_first_run_with_message_to_seller(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_buyer_message_at": None,
                "last_ai_executed_at": None,
            })
        )

    def test_should_process_order_when_buyer_replied_after_last_execution(self):
        self.assertTrue(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_ai_executed_at": "2026-06-17T10:00:00+00:00",
                "last_buyer_message_at": "2026-06-17T11:00:00+00:00",
                "ai_status": "success",
            })
        )

    def test_should_not_process_when_only_old_buyer_signal_exists(self):
        self.assertFalse(
            service.should_process_order({
                "message_to_seller": "Nome: Maria",
                "last_ai_executed_at": "2026-06-17T11:00:00+00:00",
                "last_buyer_message_at": "2026-06-17T10:00:00+00:00",
                "ai_status": "success",
            })
        )

    def test_compact_chat_messages_removes_seller_noise(self):
        messages = [
            {
                "id": "1",
                "from_user_name": "lojista",
                "to_user_name": "cliente123",
                "created_at": "2026-06-17T10:00:00",
                "type": "text",
                "display_content": "Boa tarde",
            },
            {
                "id": "2",
                "from_user_name": "cliente123",
                "to_user_name": "lojista",
                "created_at": "2026-06-17T10:01:00",
                "type": "text",
                "display_content": "Pode corrigir para Ana Clara",
            },
            {
                "id": "3",
                "from_user_name": "lojista",
                "to_user_name": "cliente123",
                "created_at": "2026-06-17T10:02:00",
                "type": "text",
                "display_content": "Nome para capa confirmado. Ana Clara\n\nSeu pedido entrou para fila de produção e em breve será postado.",
            },
        ]

        compacted = service.compact_chat_messages(messages, "cliente123")

        self.assertEqual(len(compacted), 2)
        self.assertEqual(compacted[0]["sender_role"], "Comprador")
        self.assertEqual(compacted[0]["display_content"], "Pode corrigir para Ana Clara")
        self.assertEqual(compacted[1]["sender_role"], "Vendedor")
        self.assertEqual(compacted[1]["display_content"], "Nome para capa confirmado. Ana Clara")

    def test_fetch_recent_personalized_orders_uses_all_shopee_channel_ids(self):
        query = MagicMock()
        query.select.return_value = query
        query.in_.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.gte.return_value = query
        query.execute.return_value.data = []

        with patch.object(service.supabase_db, "table", return_value=query):
            with patch.object(service, "_get_shopee_channel_ids", return_value=[1, 27]):
                service._fetch_recent_personalized_orders(recent_days=None)

        query.in_.assert_called_once_with("canal_venda_id", [1, 27])
        query.eq.assert_called_once_with("situacao_pedido_id", service.STATUS_EM_ANDAMENTO)


if __name__ == "__main__":
    unittest.main()
