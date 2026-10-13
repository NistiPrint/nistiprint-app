import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import report_service


class ReportServiceTest(unittest.TestCase):
    @patch.object(report_service.app_config_service, "get_config", return_value="7")
    @patch.object(report_service.supabase_db, "rpc")
    def test_sulfite_report_uses_confirmed_ledger_and_returns_operation_details(self, rpc, _config):
        rpc.return_value.execute.return_value = SimpleNamespace(data=[{
            "periodo": "2026-10",
            "consumo_liquido": "2.5",
            "movimentos": [{
                "movimento_id": 123,
                "tipo": "CONS_MP",
                "quantidade_liquida": 3,
                "operation_id": "11111111-1111-4111-8111-111111111111",
            }, {
                "movimento_id": 124,
                "tipo": "COMPENSACAO_CONS_MP",
                "quantidade_liquida": -0.5,
                "operation_id": "22222222-2222-4222-8222-222222222222",
            }],
        }])

        result = report_service.get_sulfite_usage_report()

        self.assertEqual(result["monthly"], {"2026-10": 2.5})
        self.assertEqual(len(result["movements_by_month"]["2026-10"]), 2)
        self.assertEqual(result["period_start"], "2026-10")
        self.assertEqual(result["source"], "confirmed_stock_movements")
        rpc.assert_called_once_with("relatorio_consumo_mensal_produto", {"p_produto_id": 7})

    @patch.object(report_service.app_config_service, "get_config", return_value="not-an-id")
    def test_sulfite_report_rejects_invalid_configured_product_id(self, _config):
        with self.assertRaisesRegex(ValueError, "ID inteiro"):
            report_service.get_sulfite_usage_report()

    @patch.object(report_service.supabase_db, "table")
    def test_production_history_uses_bounded_deterministic_pages(self, table):
        data_query, count_query = MagicMock(), MagicMock()
        table.side_effect = [data_query, count_query]
        data_query.select.return_value.neq.return_value.order.return_value.order.return_value.range.return_value.execute.return_value = SimpleNamespace(data=[
            {"id": 41, "data_registro": "2026-10-10T10:00:00", "quantidade_produzida": "2"},
        ])
        count_query.select.return_value.neq.return_value.execute.return_value = SimpleNamespace(count=41)

        result = report_service.get_producao_history(page=2, per_page=20)

        data_query.select.return_value.neq.return_value.order.return_value.order.return_value.range.assert_called_once_with(20, 39)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["per_page"], 20)
        self.assertEqual(result["total"], 41)
        self.assertTrue(result["has_next"])


if __name__ == "__main__":
    unittest.main()
