import unittest
from unittest.mock import patch

from nistiprint_shared.services.previsao_consumo_service import PrevisaoConsumoService


class PrevisaoConsumoAtomicaTest(unittest.TestCase):
    @patch("nistiprint_shared.services.previsao_consumo_service.supabase_db.rpc")
    @patch("nistiprint_shared.services.previsao_consumo_service.bom_service.get_full_bom_explosion")
    def test_composition_is_validated_before_atomic_replacement(self, explode, rpc):
        explode.side_effect = [
            [{"componente_id": 12, "quantidade_total": 2, "unidade": "un"}],
            [{"componente_id": 4, "quantidade_total": 3, "unidade": "m"}],
        ]
        rpc.return_value.execute.return_value.data = [{"status": "CONFIRMADO", "linhas": 2}]

        result = PrevisaoConsumoService().gerar_previsao_para_demanda(
            "45", [{"produto_id": 100, "quantidade": 1}, {"produto_id": 200, "quantidade": 1}]
        )

        self.assertTrue(result)
        rpc.assert_called_once_with("substituir_previsao_consumo_demanda", {
            "p_demanda_id": 45,
            "p_linhas": [
                {"produto_id": 4, "quantidade_prevista": 3, "unidade": "m"},
                {"produto_id": 12, "quantidade_prevista": 2, "unidade": "un"},
            ],
        })

    @patch("nistiprint_shared.services.previsao_consumo_service.supabase_db.rpc")
    @patch("nistiprint_shared.services.previsao_consumo_service.bom_service.get_full_bom_explosion")
    def test_invalid_new_bom_keeps_existing_forecast(self, explode, rpc):
        explode.side_effect = RuntimeError("ciclo de ficha")

        result = PrevisaoConsumoService().gerar_previsao_para_demanda(
            "45", [{"produto_id": 100, "quantidade": 1}]
        )

        self.assertFalse(result)
        rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
