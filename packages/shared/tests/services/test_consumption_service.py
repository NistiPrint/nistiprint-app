import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.consumption_service import ConsumptionService
from nistiprint_shared.services.estoque_service import EstoqueService


class ConsumptionServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = ConsumptionService()
        self.rpc_patcher = patch("nistiprint_shared.services.consumption_service.supabase_db.rpc")
        self.rpc = self.rpc_patcher.start()
        self.addCleanup(self.rpc_patcher.stop)
        self.rpc.return_value.execute.return_value.data = [
            {"produto_id": 7, "nome_insumo": "Papel", "total_periodo": "3.75",
             "media_diaria": "1.875", "periodo_dias": 2},
        ]

    def test_daily_consumption_uses_confirmed_material_movements_and_compensations(self):
        result = self.service.get_daily_consumption(days=2)

        self.assertEqual(result[7]["total_periodo"], 3.75)
        self.assertEqual(result[7]["media_diaria"], 1.875)
        self.assertEqual(result[7]["nome_insumo"], "Papel")
        self.assertNotIn(8, result)
        self.rpc.assert_called_once_with("consumo_medio_diario", {"p_dias": 2})

    def test_non_positive_period_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.get_daily_consumption(days=0)

    @patch("nistiprint_shared.services.product_service.product_service.get_by_ids")
    @patch("nistiprint_shared.services.consumption_service.consumption_service.get_daily_consumption")
    def test_abc_uses_prior_accumulation_and_keeps_first_positive_item_in_a(self, daily, products):
        daily.return_value = {
            1: {"total_periodo": 80}, 2: {"total_periodo": 10}, 3: {"total_periodo": 10},
        }
        products.return_value = {
            1: {"preco_custo": 1, "nome": "A", "sku": "A"},
            2: {"preco_custo": 1, "nome": "B", "sku": "B"},
            3: {"preco_custo": 1, "nome": "C", "sku": "C"},
        }

        result = EstoqueService().get_abc_analysis()

        self.assertEqual([item["produto_id"] for item in result["A"]], [1])
        self.assertEqual([item["produto_id"] for item in result["B"]], [2])
        self.assertEqual([item["produto_id"] for item in result["C"]], [3])

    @patch("nistiprint_shared.services.estoque_service.supabase_db.table")
    def test_inventory_valuation_separates_physical_reserved_available_and_planned(self, table):
        products_query, forecast_query = MagicMock(), MagicMock()
        table.side_effect = [products_query, forecast_query]
        products_query.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": 7, "preco_custo": 2.5, "nome": "Papel", "sku": "P-1"}
        ]
        forecast_query.select.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
            {"produto_id": 7, "quantidade_prevista": "4"}
        ]
        service = EstoqueService()
        service.get_posicao_estoque = lambda: [{
            "produto_id": 7, "saldo_atual": "10", "reservado": "3", "disponivel": "7"
        }]

        result = service.get_inventory_valuation()[0]

        self.assertEqual(result["fisico"], 10.0)
        self.assertEqual(result["reservado"], 3.0)
        self.assertEqual(result["disponivel"], 7.0)
        self.assertEqual(result["previsto"], 4.0)
        self.assertEqual(result["valor_total"], 25.0)


if __name__ == "__main__":
    unittest.main()
