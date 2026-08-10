"""Testes da rota inversa: parte dos pedidos travados na nossa base."""
import unittest
from unittest.mock import patch

from nistiprint_shared.services import ressincronizacao_service as svc


PEDIDO_ML = {
    "id": 55107,
    "marketplace_order_id": "2000017648389902",
    "origem": "MERCADOLIVRE",
    "situacao_pedido_id": 2,
    "marketplace_integration_id": 10,
    "data_venda": "2026-07-29T11:11:16",
}
PEDIDO_SHOPEE = {
    "id": 55200,
    "marketplace_order_id": "250801ABCDEF",
    "origem": "SHOPEE",
    "situacao_pedido_id": 5,
    "marketplace_integration_id": 20,
    "data_venda": "2026-08-01T09:00:00",
}
PEDIDO_AMAZON = {
    "id": 55300,
    "marketplace_order_id": "701-1234567-1234567",
    "origem": "AMAZONFBA_CLASSIC",
    "situacao_pedido_id": 5,
    "marketplace_integration_id": 30,
    "data_venda": "2026-07-31T00:00:00",
}

INTEGRACOES = {
    10: {"id": 10, "module_id": "mercadolivre", "config": {"seller_id": 207584268}},
    20: {"id": 20, "module_id": "shopee", "config": {"shop_id": 999}},
    30: {"id": 30, "module_id": "amazon", "config": {}},
}


class TestRessincronizarPendentes(unittest.TestCase):
    def test_dry_run_agrupa_sem_chamar_a_origem(self):
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_ML, PEDIDO_SHOPEE]),
            patch.object(svc.marketplace_webhook_ingest_service, "process") as process,
        ):
            resultado = svc.ressincronizar_pendentes(dry_run=True)

        self.assertTrue(resultado["dry_run"])
        self.assertEqual(resultado["listados"], 2)
        self.assertEqual(resultado["por_origem"], {"MERCADOLIVRE": 1, "SHOPEE": 1})
        process.assert_not_called()

    def test_reprocessa_pela_pipeline_do_webhook(self):
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_ML]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service,
                "process",
                return_value={"status": "success"},
            ) as process,
        ):
            resultado = svc.ressincronizar_pendentes()

        self.assertEqual(resultado["processados"], 1)
        self.assertEqual(resultado["total_erros"], 0)
        source, payload = process.call_args.args
        self.assertEqual(source, "mercadolivre")
        self.assertEqual(payload["topic"], "orders_v2")
        self.assertEqual(payload["resource"], "/orders/2000017648389902")
        self.assertEqual(payload["user_id"], 207584268)

    def test_payload_shopee_usa_shop_id_da_integracao(self):
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_SHOPEE]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service,
                "process",
                return_value={"status": "success"},
            ) as process,
        ):
            svc.ressincronizar_pendentes()

        source, payload = process.call_args.args
        self.assertEqual(source, "shopee")
        self.assertEqual(payload["shop_id"], 999)
        self.assertEqual(payload["data"]["ordersn"], "250801ABCDEF")

    def test_origem_sem_api_propria_e_contabilizada_nao_silenciada(self):
        """Amazon so tem leitura via Bling: precisa aparecer para o operador."""
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_AMAZON]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(svc.marketplace_webhook_ingest_service, "process") as process,
        ):
            resultado = svc.ressincronizar_pendentes()

        process.assert_not_called()
        self.assertEqual(resultado["processados"], 0)
        self.assertEqual(resultado["sem_rota_por_pedido"], {"AMAZONFBA_CLASSIC": 1})

    def test_falha_de_um_pedido_nao_interrompe_o_lote(self):
        with (
            patch.object(
                svc, "_pedidos_nao_finalizados",
                return_value=[PEDIDO_ML, PEDIDO_SHOPEE],
            ),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service,
                "process",
                side_effect=[RuntimeError("timeout"), {"status": "success"}],
            ),
        ):
            resultado = svc.ressincronizar_pendentes()

        self.assertEqual(resultado["processados"], 1)
        self.assertEqual(resultado["total_erros"], 1)
        self.assertEqual(resultado["erros"][0]["pedido_id"], 55107)

    def test_pedido_sem_id_do_marketplace_vira_erro_explicito(self):
        pedido = {**PEDIDO_ML, "marketplace_order_id": None}
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[pedido]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(svc.marketplace_webhook_ingest_service, "process") as process,
        ):
            resultado = svc.ressincronizar_pendentes()

        process.assert_not_called()
        self.assertEqual(resultado["total_erros"], 1)
        self.assertIn("identificador", resultado["erros"][0]["erro"])

    def test_situacoes_finais_ficam_fora_do_padrao(self):
        # 6 Entregue, 7 Cancelado, 8 Devolvido nao entram na varredura.
        self.assertEqual(svc.SITUACOES_NAO_FINALIZADAS, [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
