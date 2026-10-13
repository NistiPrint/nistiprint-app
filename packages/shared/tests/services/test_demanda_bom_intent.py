import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.demanda.items import DemandaItemsService


class ProductionIntentBomPinTests(unittest.TestCase):
    @patch("nistiprint_shared.services.demanda.items.supabase_db")
    @patch("nistiprint_shared.services.demanda.items.bom_service.publish_effective_version")
    def test_first_intent_sends_effective_bom_version_in_same_rpc(self, publish, db):
        bom_version_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        publish.return_value = {"id": bom_version_id}
        db.rpc.return_value.execute.return_value.data = {
            "success": True,
            "item": {"id": 5, "produto_id": 9, "bom_version_id": bom_version_id},
            "revision": 2,
        }
        service = DemandaItemsService()
        item = {
            "id": 5,
            "produto_id": 9,
            "operational_revision": 1,
            "bom_version_id": None,
        }

        result = service._persistir_intencao_eventos(
            item,
            {"finalizados_qtd": 1},
            [{
                "estagio": "progresso_item_atualizado",
                "quantidade_reportada": 1,
                "tipo_evento": "LIQUIDACAO",
            }],
            user_id="17",
        )

        publish.assert_called_once_with(9, actor_id="17")
        rpc_name, rpc_args = db.rpc.call_args.args
        self.assertEqual(rpc_name, "gravar_intencao_eventos_producao")
        self.assertEqual(rpc_args["p_bom_version_id"], bom_version_id)
        self.assertEqual(result["bom_version_id"], bom_version_id)

    @patch("nistiprint_shared.services.demanda.items.supabase_db")
    @patch("nistiprint_shared.services.demanda.items.bom_service.publish_effective_version")
    def test_retry_reuses_the_version_already_pinned_on_item(self, publish, db):
        bom_version_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        db.rpc.return_value.execute.return_value.data = {
            "success": True,
            "duplicate": True,
            "item": {"id": 6, "produto_id": 10, "bom_version_id": bom_version_id},
            "revision": 4,
        }
        service = DemandaItemsService()

        service._persistir_intencao_eventos(
            {"id": 6, "produto_id": 10, "bom_version_id": bom_version_id,
             "operational_revision": 4},
            {"finalizados_qtd": 2},
            [{
                "estagio": "progresso_item_atualizado",
                "quantidade_reportada": 2,
                "tipo_evento": "LIQUIDACAO",
            }],
        )

        publish.assert_not_called()
        self.assertEqual(db.rpc.call_args.args[1]["p_bom_version_id"], bom_version_id)


if __name__ == "__main__":
    unittest.main()
