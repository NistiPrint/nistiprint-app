import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.orders_query_service import OrdersQueryService


class TestOrdersQueryService(unittest.TestCase):
    def test_get_personalized_orders_v2_maps_service_rows(self):
        service_rows = [{
            "id": 1,
            "order_id": "12345",
            "shopee_order_sn": "260618ABC123",
            "marketplace_integration_id": 17,
            "order_date": "2026-06-18T10:00:00",
            "contato": {"nome": "Maria"},
            "nome_cliente": "Maria",
            "buyer_username": "maria123",
            "message_to_seller": "nome: Maria",
            "latest_buyer_message": "Pode gravar Maria Clara",
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

        with patch("nistiprint_shared.services.ai_personalization_service.get_orders_with_chats", return_value=service_rows) as get_orders:
            rows = service.get_personalized_orders_v2()

        get_orders.assert_called_once_with(situacao_ids=[2, 3, 4])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["numero"], "12345")
        self.assertEqual(rows[0]["numeroLoja"], "260618ABC123")
        self.assertEqual(rows[0]["marketplace_integration_id"], 17)
        self.assertEqual(rows[0]["shopee"]["username"], "maria123")
        self.assertEqual(rows[0]["shopee"]["message"], "Pode gravar Maria Clara")
        self.assertEqual(rows[0]["shopee"]["message_to_seller"], "nome: Maria")
        self.assertTrue(rows[0]["needs_ai_processing"])
        self.assertTrue(rows[0]["has_buyer_message"])

    def test_numeric_personalized_order_search_scans_all_accounts_before_paging(self):
        calls = []

        class Query:
            def __init__(self, table):
                self.table = table
                self.count_only = False
                self.filters = []

            def select(self, *_args, **kwargs):
                self.count_only = kwargs.get("head", False)
                return self

            def eq(self, column, value):
                self.filters.append(("eq", column, value))
                return self

            def or_(self, expression):
                self.filters.append(("or", expression))
                return self

            def order(self, *_args, **_kwargs):
                return self

            def range(self, start, end):
                self.filters.append(("range", start, end))
                return self

            def in_(self, *_args):
                return self

            def execute(self):
                calls.append((self.table, self.count_only, list(self.filters)))
                if self.table == "view_shopee_personalization_order_summary" and not self.count_only:
                    return type("Response", (), {"data": [{"id": 494099}], "count": 1})()
                if self.table == "view_vendas_personalizadas_v3":
                    return type("Response", (), {"data": []})()
                return type("Response", (), {"count": 1, "data": []})()

        class Supabase:
            def table(self, name):
                return Query(name)

        service = OrdersQueryService()
        with patch("nistiprint_shared.database.supabase_db_service.supabase_db", Supabase()):
            service.get_personalized_orders_page(
                page=1, page_size=20, search="494099", integration_id=6,
            )

        result_query = next(
            filters for table, count_only, filters in calls
            if table == "view_shopee_personalization_order_summary" and not count_only
        )
        self.assertIn(("or", "numero_pedido.ilike.%494099%,numero_loja.ilike.%494099%,nome_cliente.ilike.%494099%,buyer_username.ilike.%494099%"), result_query)
        self.assertIn(("range", 0, 19), result_query)
        self.assertFalse(any(call[:2] == ("eq", "marketplace_integration_id") for call in result_query))


if __name__ == "__main__":
    unittest.main()
