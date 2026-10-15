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
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = [{"id": 679562, "total_count": 1}]
        supabase = MagicMock()
        supabase.rpc.return_value = rpc_query
        service_rows = [{
            "id": 679562,
            "order_id": "494099",
            "shopee_order_sn": "261011B24BQVJG",
            "marketplace_integration_id": 6,
            "items": [{"id": 3, "descricao": "Caderno", "personalizations": []}],
        }]
        service = OrdersQueryService()
        with (
            patch("nistiprint_shared.database.supabase_db_service.supabase_db", supabase),
            patch("nistiprint_shared.services.ai_personalization_service.get_orders_with_chats", return_value=service_rows) as get_orders,
        ):
            service.get_personalized_orders_page(
                page=1, page_size=20, search="494", integration_id=99,
            )

        supabase.rpc.assert_called_once_with("search_personalized_shopee_order_ids", {
            "p_prefix": "494", "p_page": 1, "p_page_size": 20,
        })
        get_orders.assert_called_once_with(pedido_ids=[679562], situacao_ids=[2, 3, 4])

    def test_numeric_search_returns_same_contract_and_skips_expensive_counts(self):
        rpc_query = MagicMock()
        rpc_query.execute.return_value.data = [{"id": 1, "total_count": 1}]
        supabase = MagicMock()
        supabase.rpc.return_value = rpc_query
        with (
            patch("nistiprint_shared.database.supabase_db_service.supabase_db", supabase),
            patch("nistiprint_shared.services.ai_personalization_service.get_orders_with_chats", return_value=[]),
        ):
            result = OrdersQueryService().get_personalized_orders_page(
                page=1, page_size=20, search="123", integration_id=6,
            )

        self.assertEqual(result["pagination"], {
            "page": 1, "page_size": 20, "total": 1, "has_next": False,
        })
        self.assertIsNone(result["status_counts"])

    def test_projected_page_preserves_public_order_contract(self):
        supabase = MagicMock()
        supabase.rpc.return_value.execute.return_value.data = {
            "ready": True,
            "rows": [{
                "id": 8,
                "numero_pedido": "N-8",
                "numero_loja": "SHOP-8",
                "data_pedido": "2026-10-15T10:00:00",
                "contato": {"nome": "Ana"},
                "nome_cliente": "Ana",
                "buyer_username": "ana",
                "marketplace_integration_id": 12,
                "shopee_message": "Gravar Ana",
                "itens": [{"id": 3, "descricao": "Caneca", "personalizations": []}],
                "has_chat_messages": True,
                "needs_ai_processing": False,
            }],
            "total": 21,
            "status_counts": {"pendente_ia": 2, "com_chat": 4, "sem_chat": 5,
                              "nome_identificado": 6, "sem_nome": 7},
        }
        with patch("nistiprint_shared.database.supabase_db_service.supabase_db", supabase):
            result = OrdersQueryService().get_personalized_orders_page(
                page=2, page_size=20, integration_id=12,
            )

        supabase.rpc.assert_called_once_with("listar_pedidos_personalizados_projetados", {
            "p_page": 2, "p_page_size": 20, "p_search": "", "p_ai_filter": "",
            "p_chat_filter": "", "p_integration_id": 12, "p_include_unassigned": False,
        })
        self.assertEqual(result["pagination"], {
            "page": 2, "page_size": 20, "total": 21, "has_next": False,
        })
        self.assertEqual(result["bling_orders"][0]["numero"], "N-8")
        self.assertEqual(result["bling_orders"][0]["marketplace_integration_id"], 12)
        self.assertEqual(result["bling_orders"][0]["shopee"]["message"], "Gravar Ana")
        self.assertEqual(result["status_counts"]["sem_nome"], 7)


if __name__ == "__main__":
    unittest.main()
