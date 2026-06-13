import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from nistiprint_shared.services.logistica_coleta_service import (
    JanelaColeta,
    LogisticaColetaService,
)


class TestLogisticaColetaService(unittest.TestCase):
    def setUp(self):
        self.service = LogisticaColetaService()

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_next_window_before_first_slot(self, load_rules_mock):
        load_rules_mock.return_value = [
            JanelaColeta(1, "11:00", "13:00", "13:00", "COLETA_LOCAL", None, None, 1, [1, 2, 3, 4, 5]),
            JanelaColeta(2, "17:00", "19:00", "19:00", "PONTO_COLETA", 1, "Parceiro X", 1, [1, 2, 3, 4, 5]),
        ]
        ref = datetime(2026, 5, 18, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))  # segunda

        result = self.service.calcular_contexto_coleta(
            marketplace_integration_id=101,
            modalidade="STANDARD",
            reference_dt=ref,
        )

        self.assertTrue(result["tem_regra"])
        self.assertEqual(result["proxima_coleta_horario"], "13:00")
        self.assertEqual(result["deadline_final_horario"], "19:00")
        self.assertEqual(result["proxima_coleta_tipo_envio"], "COLETA_LOCAL")

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_next_window_between_slots_uses_backup(self, load_rules_mock):
        load_rules_mock.return_value = [
            JanelaColeta(1, "11:00", "13:00", "13:00", "COLETA_LOCAL", None, None, 1, [1, 2, 3, 4, 5]),
            JanelaColeta(2, "17:00", "19:00", "19:00", "PONTO_COLETA", 9, "Parceiro Shopee", 1, [1, 2, 3, 4, 5]),
        ]
        ref = datetime(2026, 5, 18, 15, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))  # segunda

        result = self.service.calcular_contexto_coleta(
            marketplace_integration_id=202,
            modalidade="STANDARD",
            reference_dt=ref,
        )

        self.assertEqual(result["proxima_coleta_horario"], "19:00")
        self.assertEqual(result["proxima_coleta_tipo_envio"], "PONTO_COLETA")
        self.assertEqual(result["proxima_coleta_ponto_nome"], "Parceiro Shopee")

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_next_window_after_last_slot_rolls_to_next_day(self, load_rules_mock):
        load_rules_mock.return_value = [
            JanelaColeta(1, "11:00", "13:00", "13:00", "COLETA_LOCAL", None, None, 1, [1, 2, 3, 4, 5]),
            JanelaColeta(2, "17:00", "19:00", "19:00", "PONTO_COLETA", None, None, 1, [1, 2, 3, 4, 5]),
        ]
        ref = datetime(2026, 5, 18, 20, 10, tzinfo=ZoneInfo("America/Sao_Paulo"))  # segunda

        result = self.service.calcular_contexto_coleta(
            marketplace_integration_id=303,
            modalidade="STANDARD",
            reference_dt=ref,
        )

        self.assertTrue(result["proxima_coleta_at"].startswith("2026-05-19T13:00:00"))
        self.assertEqual(result["proxima_coleta_horario"], "13:00")

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_without_rules_returns_sem_regra(self, load_rules_mock):
        load_rules_mock.return_value = []
        ref = datetime(2026, 5, 18, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

        result = self.service.calcular_contexto_coleta(
            marketplace_integration_id=404,
            modalidade="STANDARD",
            reference_dt=ref,
        )

        self.assertFalse(result["tem_regra"])
        self.assertEqual(result["janela_status"], "SEM_REGRA")

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_calcular_data_coleta_same_day_before_cutoff(self, load_rules_mock):
        load_rules_mock.return_value = [
            JanelaColeta(10, "11:00", "13:00", "13:00", "COLETA_LOCAL", None, None, 1, [1, 2, 3, 4, 5]),
        ]
        pagamento = datetime(2026, 5, 18, 10, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))

        result = self.service.calcular_data_coleta(101, "FLEX", pagamento_dt=pagamento)

        self.assertEqual(result["data_coleta"], "2026-05-18T13:00:00-03:00")
        self.assertEqual(result["horario_corte"], "11:00")
        self.assertEqual(result["regra"]["id"], 10)
        self.assertEqual(result["payment_time_source"], "payment_at")

    @patch.object(LogisticaColetaService, "_load_rules")
    def test_calcular_data_coleta_next_valid_day_after_cutoff(self, load_rules_mock):
        load_rules_mock.return_value = [
            JanelaColeta(11, "11:00", "13:00", "13:00", "COLETA_LOCAL", None, None, 1, [1, 2, 3, 4, 5]),
        ]
        pagamento = datetime(2026, 5, 18, 11, 1, tzinfo=ZoneInfo("America/Sao_Paulo"))

        result = self.service.calcular_data_coleta(101, "FLEX", pagamento_dt=pagamento)

        self.assertEqual(result["data_coleta"], "2026-05-19T13:00:00-03:00")
        self.assertEqual(result["janela_status"], "PROXIMA")


if __name__ == "__main__":
    unittest.main()
