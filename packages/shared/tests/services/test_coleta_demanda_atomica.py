import unittest
from unittest.mock import Mock, patch

from nistiprint_shared.services.demanda.collections import DemandaCollectionsService


class TestColetaDemandaAtomica(unittest.TestCase):
    def setUp(self):
        self.service = DemandaCollectionsService()
        self.service.get_demanda_with_itens = Mock(return_value={
            "id": 31, "demanda_id": "PED-A", "pedido_numero": "PED-A", "itens": [],
        })

    @patch("nistiprint_shared.services.demanda.collections.auditoria_service.log_event")
    @patch("nistiprint_shared.services.demanda.collections.supabase_db.rpc")
    def test_partial_collection_uses_stable_operation_and_single_rpc(self, rpc, audit):
        rpc.return_value = Mock(execute=Mock(return_value=Mock(data={"status": "CONFIRMADO"})))

        result = self.service.registrar_coleta_parcial(
            "PED-A", 2, "operator@example.test", "22222222-2222-4222-8222-222222222222"
        )

        self.assertEqual(result["id"], 31)
        self.assertEqual(rpc.call_args.args[0], "registrar_coleta_demanda_transacional")
        self.assertEqual(rpc.call_args.args[1]["p_demanda_id"], 31)
        self.assertEqual(rpc.call_args.args[1]["p_quantidade"], 2)
        self.assertEqual(rpc.call_args.args[1]["p_operation_id"], "22222222-2222-4222-8222-222222222222")
        audit.assert_called_once()

    @patch("nistiprint_shared.services.demanda.collections.supabase_db.rpc")
    def test_full_collection_uses_deterministic_operation_id(self, rpc):
        rpc.return_value = Mock(execute=Mock(return_value=Mock(data={"status": "CONFIRMADO"})))

        self.service.marcar_como_coletado("PED-A", "operator@example.test")
        first = rpc.call_args.args[1]["p_operation_id"]
        self.service.marcar_como_coletado("PED-A", "operator@example.test")
        second = rpc.call_args.args[1]["p_operation_id"]

        self.assertEqual(first, second)
        self.assertTrue(rpc.call_args.args[1]["p_finalizar_total"])


if __name__ == "__main__":
    unittest.main()
