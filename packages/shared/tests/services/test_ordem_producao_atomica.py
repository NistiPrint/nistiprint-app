import unittest
from unittest.mock import Mock, patch

from nistiprint_shared.services.ordem_producao_service import OrdemProducaoService


class TestOrdemProducaoAtomica(unittest.TestCase):
    def setUp(self):
        self.service = OrdemProducaoService()

    @patch("nistiprint_shared.services.ordem_producao_service.supabase_db.rpc")
    @patch("nistiprint_shared.services.ordem_producao_service.estoque_service.reservar_estoque_em_lote")
    @patch("nistiprint_shared.services.ordem_producao_service.estoque_service._resolve_deposito", return_value=4)
    @patch("nistiprint_shared.services.ordem_producao_service.app_config_service.get_config", return_value=4)
    @patch("nistiprint_shared.services.ordem_producao_service.product_service.get_by_id", return_value={"nome": "Papel", "sku": "P-1"})
    @patch("nistiprint_shared.services.ordem_producao_service.bom_service.publish_effective_version")
    def test_inicio_envia_reserva_e_estado_em_uma_rpc_idempotente(
        self, publish_bom, get_product, get_config, resolve_deposit, legacy_reserve, rpc
    ):
        publish_bom.return_value = {
            "id": "11111111-1111-4111-8111-111111111111",
            "graph": {"nodes": {"10": {"componentes": [
                {"componente_id": 20, "quantidade_necessaria": 2},
            ]}}},
        }
        self.service.get_by_id = Mock(return_value={
            "id": "7", "produto_id": 10, "quantidade": 3, "status": "DRAFT",
        })
        execute = Mock(return_value=Mock(data={"ordem_producao": {"id": 7, "status": "PENDING"}}))
        rpc.return_value = Mock(execute=execute)

        first = self.service.start_production("7")
        first_call = rpc.call_args
        second = self.service.start_production("7")

        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(second["status"], "PENDING")
        self.assertEqual(first_call.args[1]["p_operation_id"], rpc.call_args.args[1]["p_operation_id"])
        self.assertEqual(first_call.args[1]["p_content_hash"], rpc.call_args.args[1]["p_content_hash"])
        self.assertEqual(first_call.args[1]["p_needs"][0]["componente_id"], 20)
        legacy_reserve.assert_not_called()

    @patch("nistiprint_shared.services.ordem_producao_service.supabase_db.rpc")
    @patch("nistiprint_shared.services.ordem_producao_service.estoque_service.liberar_reserva")
    def test_cancelamento_nao_tenta_liberar_por_escrita_legada(self, legacy_release, rpc):
        self.service.get_by_id = Mock(return_value={"id": "7", "status": "PENDING"})
        rpc.return_value = Mock(execute=Mock(return_value=Mock(data={
            "ordem_producao": {"id": 7, "status": "CANCELED"},
        })))

        result = self.service.cancel_production("7")

        self.assertEqual(result["status"], "CANCELED")
        self.assertEqual(rpc.call_args.args[0], "cancelar_ordem_producao_transacional")
        legacy_release.assert_not_called()

    @patch("nistiprint_shared.services.demanda_producao_service.demanda_producao_service.alocar_producao_automatica")
    @patch("nistiprint_shared.services.ordem_producao_service.supabase_db.rpc")
    @patch("nistiprint_shared.services.ordem_producao_service.estoque_service._resolve_deposito", return_value=4)
    def test_repeticao_de_entrega_retorna_resultado_sem_realocar_demanda(
        self, resolve_deposit, rpc, demand_service
    ):
        rpc.return_value = Mock(execute=Mock(return_value=Mock(data={
            "replayed": True,
            "ordem_producao": {"id": 7, "produto_id": 10, "status": "COMPLETED"},
            "snapshot_componentes": [],
        })))

        result, snapshot = self.service.deliver_production(
            "7", 1, operation_id="22222222-2222-4222-8222-222222222222"
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(snapshot, [])
        self.assertEqual(rpc.call_args.args[0], "entregar_ordem_producao_transacional")
        demand_service.alocar_producao_automatica.assert_not_called()


if __name__ == "__main__":
    unittest.main()
