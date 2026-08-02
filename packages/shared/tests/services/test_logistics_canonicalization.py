"""Canonizacao logistica — prazo de postagem, modalidade e comprador.

Os payloads usados aqui foram extraidos de `pedido_snapshots` em producao
(02/08/2026), nao inventados. A distribuicao real que sustenta o mapeamento:

    Shopee    Shopee Xpress / fulfilled_by_local_seller   1024  -> STANDARD
              Full / fulfilled_by_shopee                   239  -> FULFILLMENT
              Entrega Rapida / fulfilled_by_local_seller   123  -> FLEX
              Retirada pelo Comprador                       11  -> RETIRADA

    ML        me2 / xd_drop_off                             95  -> STANDARD
              me2 / fulfillment                             20  -> FULFILLMENT
              me2 / self_service                             4  -> FLEX
"""
import unittest
from datetime import datetime, timezone

from nistiprint_shared.services import logistics_canonicalization as L


class TestPrazoDePostagem(unittest.TestCase):
    """`data_limite_envio` e prazo de POSTAGEM, nao de entrega."""

    def test_shopee_usa_ship_by_date(self):
        r = L.resolve("shopee", {"ship_by_date": "2026-08-05T23:59:59-03:00"})
        self.assertTrue(r.data_limite_envio.startswith("2026-08-05"))
        self.assertEqual(r.dispatch_deadline_source, "shopee.ship_by_date")

    def test_meli_prefere_o_endpoint_de_sla(self):
        """`/shipments/{id}/sla` e a fonte autoritativa do prazo de postagem.

        Cobre 280 de 317 snapshots (88%) contra 60 (19%) de `buffering`.
        """
        detalhe = {
            "sla": {"expected_date": "2026-08-03T23:59:59-03:00", "status": "on_time"},
            "shipment": {
                "logistic": {"mode": "me2", "type": "xd_drop_off"},
                "lead_time": {"buffering": {"date": "2026-08-09T00:00:00.000Z"}},
            },
        }
        r = L.resolve("mercadolivre", detalhe)
        self.assertTrue(r.data_limite_envio.startswith("2026-08-03"))
        self.assertEqual(r.dispatch_deadline_source, "mercadolivre.sla.expected_date")

    def test_meli_aceita_sla_como_lista(self):
        """O ingest direto guarda objeto; o caminho Bling guarda lista."""
        detalhe = {"sla": [{"expected_date": "2026-08-03T23:59:59-03:00"}]}
        r = L.resolve("mercadolivre", detalhe)
        self.assertTrue(r.data_limite_envio.startswith("2026-08-03"))

    def test_meli_cai_para_buffering_sem_sla(self):
        detalhe = {
            "sla": {},
            "shipment": {"lead_time": {"buffering": {"date": "2026-08-03T00:00:00.000Z"}}},
        }
        r = L.resolve("mercadolivre", detalhe)
        self.assertTrue(r.data_limite_envio.startswith("2026-08-03"))
        self.assertIn("buffering", r.dispatch_deadline_source)

    def test_meli_nunca_usa_prazo_de_entrega(self):
        """`estimated_delivery_time` inclui transporte e nao serve."""
        detalhe = {
            "shipment": {
                "lead_time": {
                    "estimated_delivery_time": {"date": "2026-08-11T00:00:00.000-03:00"}
                }
            }
        }
        self.assertIsNone(L.resolve("mercadolivre", detalhe).data_limite_envio)

    def test_prazo_ausente_nao_e_inventado(self):
        """Derivar de date_created+handling daria numero errado: handling vem 0."""
        detalhe = {
            "shipment": {
                "date_created": "2026-08-01T22:00:00-03:00",
                "logistic": {"type": "xd_drop_off"},
                "lead_time": {"estimated_delivery_time": {"handling": 0}},
            }
        }
        r = L.resolve("mercadolivre", detalhe)
        self.assertIsNone(r.data_limite_envio)
        self.assertIn("nao informado", r.reason)

    def test_aceita_epoch(self):
        epoch = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())
        r = L.resolve("shopee", {"ship_by_date": epoch})
        self.assertTrue(r.data_limite_envio.startswith("2026-08-05"))

    def test_aceita_epoch_como_string(self):
        epoch = str(int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp()))
        r = L.resolve("shopee", {"ship_by_date": epoch})
        self.assertTrue(r.data_limite_envio.startswith("2026-08-05"))

    def test_aceita_sufixo_z(self):
        self.assertIsNotNone(L.normalize_deadline("2026-08-03T00:00:00.000Z"))

    def test_valores_invalidos_viram_none(self):
        for ruim in (None, "", 0, "amanha", "não sei"):
            self.assertIsNone(L.normalize_deadline(ruim), f"falhou para {ruim!r}")

    def test_shopee_le_do_raw_quando_ausente_no_topo(self):
        r = L.resolve("shopee", {"raw": {"ship_by_date": "2026-08-05T23:59:59-03:00"}})
        self.assertIsNotNone(r.data_limite_envio)


class TestModalidade(unittest.TestCase):
    def _shopee(self, carrier, flag="fulfilled_by_local_seller"):
        return L.resolve(
            "shopee", {"shipping_carrier": carrier, "fulfillment_flag": flag}
        ).modalidade_logistica

    def _meli(self, tipo):
        return L.resolve(
            "mercadolivre", {"shipment": {"logistic": {"mode": "me2", "type": tipo}}}
        ).modalidade_logistica

    def test_shopee_casos_reais(self):
        self.assertEqual(self._shopee("Shopee Xpress"), L.STANDARD)
        self.assertEqual(self._shopee("Entrega Rápida"), L.FLEX)
        self.assertEqual(self._shopee("Retirada pelo Comprador"), L.RETIRADA)
        self.assertEqual(self._shopee("Full", "fulfilled_by_shopee"), L.FULFILLMENT)

    def test_shopee_sem_acento_tambem_casa(self):
        self.assertEqual(self._shopee("Entrega Rapida"), L.FLEX)

    def test_meli_casos_reais(self):
        self.assertEqual(self._meli("xd_drop_off"), L.STANDARD)
        self.assertEqual(self._meli("self_service"), L.FLEX)
        self.assertEqual(self._meli("fulfillment"), L.FULFILLMENT)

    def test_meli_le_logistic_type_aninhado(self):
        """O ingest lia `shipment.logistic_type`; o payload real usa
        `shipment.logistic.type`. Era por isso que nenhum ML virava FLEX."""
        aninhado = {"shipment": {"logistic": {"type": "self_service"}}}
        self.assertEqual(L.resolve("mercadolivre", aninhado).modalidade_logistica, L.FLEX)

    def test_meli_formato_antigo_ainda_funciona(self):
        antigo = {"shipment": {"logistic_type": "self_service"}}
        self.assertEqual(L.resolve("mercadolivre", antigo).modalidade_logistica, L.FLEX)

    def test_fulfilled_by_local_seller_nao_vira_fulfillment(self):
        """A armadilha: 'full' esta contido em 'fulfilled_by_local_seller'.

        Casar por substring transformaria os 1.024 pedidos STANDARD em
        FULFILLMENT — e pedido fulfillment nao e produzido nem despachado por
        nos, entao o erro sumiria com eles da producao.
        """
        self.assertEqual(self._shopee("Shopee Xpress", "fulfilled_by_local_seller"), L.STANDARD)

    def test_flags_derivadas_sao_coerentes(self):
        flex = L.resolve("shopee", {"shipping_carrier": "Entrega Rápida"})
        self.assertTrue(flex.is_flex)
        self.assertFalse(flex.is_fulfillment)

        full = L.resolve("shopee", {"fulfillment_flag": "fulfilled_by_shopee"})
        self.assertTrue(full.is_fulfillment)
        self.assertFalse(full.is_flex)

    def test_sem_sinal_assume_standard(self):
        r = L.resolve("shopee", {})
        self.assertEqual(r.modalidade_logistica, L.STANDARD)
        self.assertIn("STANDARD por omissao", r.reason)

    def test_express_e_alias_de_flex(self):
        self.assertEqual(L.canonical_modalidade("EXPRESS"), L.FLEX)

    def test_modalidade_desconhecida_e_rejeitada(self):
        self.assertIsNone(L.canonical_modalidade("SEDEX"))


class TestIdentidadeDoComprador(unittest.TestCase):
    """`buyer_username` e exclusivo da Shopee."""

    def test_shopee_extrai_username_e_id(self):
        r = L.resolve(
            "shopee", {"buyer_username": "vihdani", "buyer_user_id": 250570466}
        )
        self.assertEqual(r.buyer_username, "vihdani")
        self.assertEqual(r.buyer_user_id, 250570466)

    def test_meli_nao_tem_username(self):
        r = L.resolve("mercadolivre", {"shipment": {"logistic": {"type": "xd_drop_off"}}})
        self.assertIsNone(r.buyer_username)

    def test_username_em_branco_vira_none(self):
        self.assertIsNone(L.resolve("shopee", {"buyer_username": "   "}).buyer_username)

    def test_buyer_id_nao_numerico_nao_quebra(self):
        r = L.resolve("shopee", {"buyer_user_id": "abc", "buyer_username": "x"})
        self.assertIsNone(r.buyer_user_id)
        self.assertEqual(r.buyer_username, "x")

    def test_username_e_lido_do_raw(self):
        r = L.resolve("shopee", {"raw": {"buyer_username": "vihdani"}})
        self.assertEqual(r.buyer_username, "vihdani")


class TestContratoDeSaida(unittest.TestCase):
    def test_to_order_fields_omite_nulos(self):
        campos = L.resolve("mercadolivre", {"shipment": {}}).to_order_fields()
        self.assertNotIn("data_limite_envio", campos)
        self.assertNotIn("buyer_username", campos)
        # Modalidade e flags sempre existem: o pedido tem de ter uma.
        self.assertEqual(campos["modalidade_logistica"], L.STANDARD)
        self.assertIn("is_flex", campos)

    def test_provider_desconhecido_nao_quebra(self):
        r = L.resolve("shein", {"qualquer": "coisa"})
        self.assertEqual(r.modalidade_logistica, L.STANDARD)
        self.assertIsNone(r.data_limite_envio)

    def test_detalhe_nulo_nao_quebra(self):
        self.assertEqual(L.resolve("shopee", None).modalidade_logistica, L.STANDARD)

    def test_motivo_sempre_explica_a_decisao(self):
        r = L.resolve("shopee", {"shipping_carrier": "Entrega Rápida"})
        self.assertIn("FLEX", r.reason)


if __name__ == "__main__":
    unittest.main()
