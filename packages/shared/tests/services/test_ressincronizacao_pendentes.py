"""Testes da rota inversa: parte dos pedidos travados na nossa base."""
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import ressincronizacao_service as svc


PEDIDO_ML = {
    "id": 55107,
    "marketplace_order_id": "2000017648389902",
    "origem": "MERCADOLIVRE",
    "situacao_pedido_id": 2,
    "marketplace_integration_id": 10,
    "data_venda": "2026-07-29T11:11:16",
    "erp_order_id": 26480797174,
    "erp_integration_id": 1,
}
PEDIDO_SHOPEE = {
    "id": 55200,
    "marketplace_order_id": "250801ABCDEF",
    "origem": "SHOPEE",
    "situacao_pedido_id": 5,
    "marketplace_integration_id": 20,
    "data_venda": "2026-08-01T09:00:00",
    "erp_order_id": 26480797175,
    "erp_integration_id": 1,
}
PEDIDO_AMAZON = {
    "id": 55300,
    "marketplace_order_id": "701-1234567-1234567",
    "origem": "AMAZONFBA_CLASSIC",
    "situacao_pedido_id": 5,
    "marketplace_integration_id": 30,
    "data_venda": "2026-07-31T00:00:00",
    "erp_order_id": 26480799999,
    "erp_integration_id": 2,
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
        self.assertEqual(resultado["por_rota"]["direta"], 1)
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

    def test_origem_sem_api_propria_e_relida_no_bling(self):
        """Amazon nao tem API propria aqui, mas o Bling e integrado com ela.

        Descartar essas origens como 'sem rota' jogava fora status que existe —
        e sao justamente as origens em que o webhook e o unico canal.
        """
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_AMAZON]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(svc.marketplace_webhook_ingest_service, "process") as process,
            patch.object(svc, "_reler_no_bling", return_value={"status": "success"}) as bling,
        ):
            resultado = svc.ressincronizar_pendentes()

        process.assert_not_called()
        bling.assert_called_once()
        self.assertEqual(bling.call_args.args[0]["id"], 55300)
        self.assertEqual(resultado["processados"], 1)
        self.assertEqual(resultado["por_rota"], {"direta": 0, "bling": 1})

    def test_marketplace_sem_integracao_cai_para_o_bling(self):
        """Sem vinculo de marketplace nao ha leitura direta, mas ha a do ERP."""
        pedido = {**PEDIDO_ML, "marketplace_integration_id": None}
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[pedido]),
            patch.object(svc, "_integracoes_por_id", return_value={}),
            patch.object(svc, "_reler_no_bling", return_value={"status": "success"}) as bling,
        ):
            resultado = svc.ressincronizar_pendentes()

        bling.assert_called_once()
        self.assertEqual(resultado["por_rota"]["bling"], 1)

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
        self.assertEqual(resultado["erros"][0]["rota"], "direta")

    def test_falha_da_rota_bling_nao_interrompe_o_lote(self):
        with (
            patch.object(
                svc, "_pedidos_nao_finalizados",
                return_value=[PEDIDO_AMAZON, PEDIDO_SHOPEE],
            ),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(svc, "_reler_no_bling", side_effect=RuntimeError("429")),
            patch.object(
                svc.marketplace_webhook_ingest_service,
                "process",
                return_value={"status": "success"},
            ),
        ):
            resultado = svc.ressincronizar_pendentes()

        self.assertEqual(resultado["processados"], 1)
        self.assertEqual(resultado["total_erros"], 1)
        self.assertEqual(resultado["erros"][0]["rota"], "bling")

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

    def test_pedido_ids_restringe_a_consulta(self):
        """Desafogar um conjunto conhecido nao pode custar uma varredura inteira."""
        with (
            patch.object(
                svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_ML],
            ) as consulta,
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service, "process",
                return_value={"status": "success"},
            ),
        ):
            svc.ressincronizar_pendentes(pedido_ids=[55107, 55200])

        self.assertEqual(
            consulta.call_args.kwargs["pedido_ids"], [55107, 55200]
        )

    def test_situacoes_finais_ficam_fora_do_padrao(self):
        # 6 Entregue, 7 Cancelado, 8 Devolvido nao entram na varredura.
        self.assertEqual(svc.SITUACOES_NAO_FINALIZADAS, [1, 2, 3, 4, 5])


class TestCursorDaVarredura(unittest.TestCase):
    """O cursor e o que impede a varredura de reprocessar sempre o mesmo topo."""

    def test_lote_cheio_avanca_o_cursor_para_o_ultimo_id(self):
        with (
            patch.object(svc, "_ler_cursor", return_value=0),
            patch.object(
                svc, "_pedidos_nao_finalizados",
                return_value=[PEDIDO_ML, PEDIDO_SHOPEE],
            ),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service, "process",
                return_value={"status": "success"},
            ),
            patch.object(svc, "_gravar_cursor") as gravar,
        ):
            resultado = svc.ressincronizar_pendentes(limite=2, usar_cursor=True)

        gravar.assert_called_once_with(55200)
        self.assertEqual(resultado["cursor_final"], 55200)

    def test_lote_parcial_zera_o_cursor_para_dar_a_volta(self):
        with (
            patch.object(svc, "_ler_cursor", return_value=55000),
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_ML]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service, "process",
                return_value={"status": "success"},
            ),
            patch.object(svc, "_gravar_cursor") as gravar,
        ):
            resultado = svc.ressincronizar_pendentes(limite=100, usar_cursor=True)

        gravar.assert_called_once_with(0)
        self.assertEqual(resultado["cursor_inicial"], 55000)

    def test_fim_da_base_reinicia_a_varredura_no_mesmo_ciclo(self):
        """Cursor no fim nao pode significar uma execucao desperdicada."""
        lotes = [[], [PEDIDO_ML]]
        with (
            patch.object(svc, "_ler_cursor", return_value=99999),
            patch.object(
                svc, "_pedidos_nao_finalizados", side_effect=lotes,
            ) as consulta,
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service, "process",
                return_value={"status": "success"},
            ),
            patch.object(svc, "_gravar_cursor") as gravar,
        ):
            resultado = svc.ressincronizar_pendentes(limite=100, usar_cursor=True)

        self.assertEqual(consulta.call_count, 2)
        self.assertIsNone(consulta.call_args_list[1].kwargs.get("depois_do_id"))
        self.assertEqual(resultado["processados"], 1)
        gravar.assert_called_once_with(0)

    def test_disparo_manual_nao_move_o_cursor_da_varredura(self):
        with (
            patch.object(svc, "_pedidos_nao_finalizados", return_value=[PEDIDO_ML]),
            patch.object(svc, "_integracoes_por_id", return_value=INTEGRACOES),
            patch.object(
                svc.marketplace_webhook_ingest_service, "process",
                return_value={"status": "success"},
            ),
            patch.object(svc, "_gravar_cursor") as gravar,
        ):
            svc.ressincronizar_pendentes(limite=100)

        gravar.assert_not_called()


class TestReleituraNoBling(unittest.TestCase):
    def test_le_por_erp_order_id_e_devolve_para_a_pipeline(self):
        detalhe = {"id": 26480799999, "numeroLoja": "701-1234567-1234567"}
        cliente = MagicMock()
        cliente.get_order.return_value = detalhe

        with (
            patch.object(
                svc.bling_client_resolver_service, "resolve_client",
                return_value=(cliente, 2),
            ) as resolve,
            patch(
                "nistiprint_shared.services.bling_order_processing_service.process_webhook",
                return_value={"status": "success"},
            ) as process_webhook,
        ):
            resultado = svc._reler_no_bling(PEDIDO_AMAZON, "corr-1")

        cliente.get_order.assert_called_once_with(26480799999)
        self.assertEqual(resolve.call_args.kwargs["bling_integration_id"], 2)
        self.assertEqual(process_webhook.call_args.args[0], detalhe)
        self.assertEqual(
            process_webhook.call_args.kwargs["bling_integration_hint"], 2
        )
        self.assertEqual(resultado["status"], "success")

    def test_pedido_sem_erp_order_id_falha_explicitamente(self):
        pedido = {**PEDIDO_AMAZON, "erp_order_id": None}
        with self.assertRaises(ValueError):
            svc._reler_no_bling(pedido, "corr-1")

    def test_pedido_ausente_no_bling_vira_erro(self):
        cliente = MagicMock()
        cliente.get_order.return_value = None
        with patch.object(
            svc.bling_client_resolver_service, "resolve_client",
            return_value=(cliente, 2),
        ):
            with self.assertRaises(RuntimeError):
                svc._reler_no_bling(PEDIDO_AMAZON, "corr-1")


if __name__ == "__main__":
    unittest.main()
