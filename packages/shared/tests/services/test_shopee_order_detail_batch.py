"""Detalhe de pedidos Shopee em lote.

`get_order_detail` aceita lista na assinatura mas tem semantica de pedido unico
(le `order_list[0]`). Passar 50 ali devolveria so o primeiro, em silencio. Estes
testes fixam o contrato da versao em lote: indexada por `order_sn`, sem nunca
deixar um pedido herdar o detalhe de outro.
"""
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services.platform_drivers import shopee


CREDENCIAIS = {
    "partner_id": "1",
    "partner_key": "k",
    "shop_id": "999",
    "access_token": "t",
}


def _resposta(order_sns):
    valor = {
        "response": {
            "order_list": [
                {"order_sn": sn, "order_status": "READY_TO_SHIP", "total_amount": 10}
                for sn in order_sns
            ]
        }
    }
    return MagicMock(ok=True, value=valor)


class TestGetOrderDetailsBatch(unittest.TestCase):
    def setUp(self):
        self._creds = patch.object(
            shopee, "_resolve_credentials", return_value=CREDENCIAIS
        )
        self._sign = patch.object(shopee, "_generate_sign", return_value="sig")
        self._creds.start()
        self._sign.start()
        self.addCleanup(self._creds.stop)
        self.addCleanup(self._sign.stop)

    def test_cinquenta_pedidos_em_uma_unica_chamada(self):
        sns = [f"25080{i:04d}" for i in range(50)]
        with patch.object(shopee, "request_json", return_value=_resposta(sns)) as req:
            resultado = shopee.get_order_details_batch({}, sns)

        self.assertEqual(req.call_count, 1)
        self.assertEqual(len(resultado), 50)
        enviados = req.call_args.kwargs["params"]["order_sn_list"].split(",")
        self.assertEqual(len(enviados), 50)

    def test_acima_do_teto_quebra_em_lotes_de_cinquenta(self):
        sns = [f"25080{i:04d}" for i in range(120)]
        with patch.object(
            shopee, "request_json",
            side_effect=lambda *a, **kw: _resposta(
                kw["params"]["order_sn_list"].split(",")
            ),
        ) as req:
            resultado = shopee.get_order_details_batch({}, sns)

        self.assertEqual(req.call_count, 3)
        self.assertEqual(len(resultado), 120)

    def test_resultado_e_indexado_pelo_order_sn_pedido(self):
        """Sem indexar por chave, um pedido herdaria o detalhe do vizinho."""
        sns = ["250801AAAAAA", "250801BBBBBB", "250801CCCCCC"]
        with patch.object(
            shopee, "request_json",
            return_value=_resposta(["250801CCCCCC", "250801AAAAAA", "250801BBBBBB"]),
        ):
            resultado = shopee.get_order_details_batch({}, sns)

        for sn in sns:
            self.assertEqual(resultado[sn]["external_id"], sn)

    def test_pedido_ausente_na_resposta_vira_erro_proprio(self):
        with patch.object(shopee, "request_json", return_value=_resposta(["250801AAAAAA"])):
            resultado = shopee.get_order_details_batch(
                {}, ["250801AAAAAA", "250801SUMIU0"]
            )

        self.assertEqual(resultado["250801AAAAAA"]["external_id"], "250801AAAAAA")
        self.assertEqual(
            resultado["250801SUMIU0"]["error_type"], "provider_resource_not_found"
        )

    def test_order_sn_invalido_nao_derruba_o_lote(self):
        with patch.object(shopee, "request_json", return_value=_resposta(["250801AAAAAA"])):
            resultado = shopee.get_order_details_batch({}, ["250801AAAAAA", "x/y"])

        self.assertEqual(resultado["250801AAAAAA"]["external_id"], "250801AAAAAA")
        self.assertEqual(
            resultado["x/y"]["error_type"], "invalid_provider_resource_id"
        )

    def test_falha_de_lote_nao_vira_pedido_nao_encontrado(self):
        """Sao coisas diferentes: uma justifica retry, a outra nao."""
        falha = MagicMock(ok=False)
        falha.to_legacy.return_value = {"error": "429", "error_type": "rate_limited"}
        with patch.object(shopee, "request_json", return_value=falha):
            resultado = shopee.get_order_details_batch(
                {}, ["250801AAAAAA", "250801BBBBBB"]
            )

        for sn in ("250801AAAAAA", "250801BBBBBB"):
            self.assertEqual(resultado[sn]["error_type"], "rate_limited")

    def test_lista_vazia_nao_chama_a_api(self):
        with patch.object(shopee, "request_json") as req:
            self.assertEqual(shopee.get_order_details_batch({}, []), {})
        req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
