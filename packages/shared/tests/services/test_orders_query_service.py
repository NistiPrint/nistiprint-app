import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.orders_query_service import OrdersQueryService


class TestOrdersQueryService(unittest.TestCase):
    def test_get_personalized_orders_v2_maps_service_rows(self):
        service_rows = [{
            "id": 1,
            "order_id": "12345",
            "shopee_order_sn": "260618ABC123",
            "order_date": "2026-06-18T10:00:00",
            "contato": {"nome": "Maria"},
            "nome_cliente": "Maria",
            "buyer_username": "maria123",
            "message_to_seller": "nome: Maria",
            "has_chat_messages": True,
            "has_buyer_message": True,
            "needs_ai_processing": True,
            "ai_status": "NOT_PROCESSED",
            "items": [{
                "id": 10,
                "descricao": "Planner personalizado",
                "personalizations": [],
            }],
        }]

        service = OrdersQueryService()

        with patch("nistiprint_shared.services.ai_personalization_service.get_orders_with_chats", return_value=service_rows):
            rows = service.get_personalized_orders_v2()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numero"], "12345")
        self.assertEqual(rows[0]["numeroLoja"], "260618ABC123")
        self.assertEqual(rows[0]["shopee"]["username"], "maria123")
        self.assertEqual(rows[0]["shopee"]["message"], "nome: Maria")
        self.assertTrue(rows[0]["needs_ai_processing"])
        self.assertTrue(rows[0]["has_buyer_message"])


if __name__ == "__main__":
    unittest.main()
