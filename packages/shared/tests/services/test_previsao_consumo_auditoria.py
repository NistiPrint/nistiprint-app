import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.previsao_consumo_service import PrevisaoConsumoService


class PrevisaoConsumoAuditoriaTest(unittest.TestCase):
    @patch("nistiprint_shared.services.previsao_consumo_service.supabase_db.table")
    def test_audita_movimentos_por_item_e_compensacoes_sem_busca_textual(self, table):
        forecast = MagicMock()
        forecast.select.return_value.eq.return_value.execute.return_value.data = [{
            "produto_id": "12", "quantidade_prevista": 8, "unidade": "un",
            "produtos": {"nome": "Papel", "sku": "P-12"},
        }]
        items = MagicMock()
        items.select.return_value.eq.return_value.execute.return_value.data = [{"id": 91}]
        linked = MagicMock()
        linked.select.return_value.in_.return_value.execute.return_value.data = [
            {"id": 1, "produto_id": 12, "quantidade": -6, "tipo_movimentacao": "CONS_MP",
             "data_movimentacao": "2026-10-08T10:00:00Z", "operation_id": "op-1",
             "item_demanda_id": 91, "documento_referencia": None, "correlation_id": "c-1"},
            {"id": 2, "produto_id": "12", "quantidade": 2, "tipo_movimentacao": "ESTORNO_CONS_MP",
             "data_movimentacao": "2026-10-08T11:00:00Z", "operation_id": "op-2",
             "item_demanda_id": 91, "documento_referencia": None, "correlation_id": "c-2"},
        ]
        legacy = MagicMock()
        legacy.select.return_value.eq.return_value.execute.return_value.data = []
        table.side_effect = [forecast, items, linked, legacy]

        result = PrevisaoConsumoService().audit_consumption_for_demand("7")

        self.assertTrue(result["success"])
        row = result["audit_report"][0]
        self.assertEqual(row["realizado"], 4.0)
        self.assertEqual(row["diferenca"], 4.0)
        self.assertEqual([m["operation_id"] for m in row["movimentos"]], ["op-1", "op-2"])
        self.assertEqual(result["period_start"], "2026-10-08T10:00:00Z")
        self.assertEqual(result["period_end"], "2026-10-08T11:00:00Z")
        self.assertFalse(any("ilike" in repr(call) for call in table.mock_calls))


if __name__ == "__main__":
    unittest.main()
