import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from nistiprint_shared.services.logistica_coleta_service import LogisticaColetaService


class TestLogisticaColetaService(unittest.TestCase):
    def setUp(self):
        self.service = LogisticaColetaService()

    @patch("nistiprint_shared.services.logistica_coleta_service.rpc_data")
    def test_payment_has_precedence_and_naive_datetime_uses_local_timezone(self, rpc):
        rpc.return_value = {"data_coleta": "2026-10-02T14:00:00-03:00", "regra": {"id": 12}}
        result = self.service.calcular_data_coleta(101, "STANDARD", pagamento_dt=datetime(2026, 10, 2, 13), compra_dt=datetime(2026, 10, 2, 9))
        self.assertEqual(rpc.call_args.args[1]["p_referencia"], "2026-10-02T13:00:00-03:00")
        self.assertEqual(result["payment_time_source"], "payment_at")
        self.assertEqual(result["regra"]["id"], 12)

    @patch("nistiprint_shared.services.logistica_coleta_service.rpc_data")
    def test_context_uses_sql_calendar_with_clock_without_reimplementing_it(self, rpc):
        rpc.return_value = {"tem_regra": True, "janela_status": "SEM_ATENDIMENTO"}
        clock = datetime(2026, 10, 3, 10, tzinfo=ZoneInfo("America/Sao_Paulo"))
        result = self.service.calcular_contexto_coleta(101, "NEW_MODALITY", reference_dt=clock)
        rpc.assert_called_once_with("logistica_contexto_coleta", {"p_integration_id": 101, "p_modalidade": "NEW_MODALITY", "p_agora": clock.isoformat()})
        self.assertEqual(result["janela_status"], "SEM_ATENDIMENTO")

    @patch("nistiprint_shared.services.logistica_coleta_service.rpc_data")
    def test_no_account_does_not_query_a_default_calendar(self, rpc):
        self.assertFalse(self.service.calcular_data_coleta(None, "STANDARD")["tem_regra"])
        rpc.assert_not_called()
