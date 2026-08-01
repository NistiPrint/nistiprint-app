"""Casos normativos da §10 de `docs/specs/03-contracts/canonizacao-status-pedido.md`.

Cada teste referencia o numero do caso na spec. Os casos 16 e 17 sao de
identidade/idempotencia do ingest e vivem no banco (indice unico de
`marketplace_order_transitions` e chave de loja + order_sn); aqui e testado o
que cabe a esta camada: a decisao e deterministica e independente de ordem.
"""
import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_lifecycle_service import (
    resolve_bling,
    resolve_mercadolivre,
    resolve_shopee,
)
from nistiprint_shared.services.order_status_decision import (
    is_authoritative,
    project_operational_status,
)
from nistiprint_shared.services.order_status_lexicon import LexiconResolver

PENDING, PAID, PRODUCED, READY = 1, 2, 3, 4
SHIPPED, DELIVERED, CANCELLED, RETURNED = 5, 6, 7, 8


def _offline() -> LexiconResolver:
    """Lexico preso ao SEED: os testes nao dependem do banco."""
    resolver = LexiconResolver()
    with patch.object(resolver, "_load_overrides", return_value={}):
        resolver._overrides()
    return resolver


class ShopeeCases(unittest.TestCase):
    def setUp(self):
        self.lex = _offline()

    def _shopee(self, status, webhook=None):
        return resolve_shopee(
            {"order_status": status}, webhook, resolver=self.lex
        )

    def test_case_01_full_sequence(self):
        sequence = ["UNPAID", "READY_TO_SHIP", "PROCESSED", "SHIPPED", "COMPLETED"]
        expected = [PENDING, PAID, READY, SHIPPED, DELIVERED]
        situacao = None
        applied = []
        for status in sequence:
            situacao = project_operational_status(
                situacao, self._shopee(status).target_situacao_pedido_id
            )
            applied.append(situacao)
        self.assertEqual(applied, expected)

    def test_case_02_processed_after_shipped_does_not_regress(self):
        self.assertEqual(
            project_operational_status(
                SHIPPED, self._shopee("PROCESSED").target_situacao_pedido_id
            ),
            SHIPPED,
        )

    def test_case_11_in_cancel_refused_then_shipped(self):
        situacao = PAID
        situacao = project_operational_status(
            situacao, self._shopee("IN_CANCEL").target_situacao_pedido_id
        )
        self.assertEqual(situacao, PAID)
        situacao = project_operational_status(
            situacao, self._shopee("SHIPPED").target_situacao_pedido_id
        )
        self.assertEqual(situacao, SHIPPED)

    def test_case_15_unknown_status_is_reported_not_guessed(self):
        result = self._shopee("SOME_NEW_STATUS")
        self.assertEqual(result.lifecycle_stage, "unknown")
        self.assertIsNone(result.target_situacao_pedido_id)
        self.assertEqual(project_operational_status(PAID, None), PAID)

    def test_partial_refund_does_not_close_the_order(self):
        result = resolve_shopee(
            {"order_status": "COMPLETED", "return_status": "PARTIAL_REFUND"},
            resolver=self.lex,
        )
        self.assertEqual(result.lifecycle_stage, "partially_refunded")
        self.assertEqual(result.target_situacao_pedido_id, DELIVERED)


class MercadoLivreCases(unittest.TestCase):
    def setUp(self):
        self.lex = _offline()

    def _meli(self, detail, webhook=None):
        return resolve_mercadolivre(detail, webhook, resolver=self.lex)

    def test_case_03_payment_then_dispatch_substatus(self):
        paid = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "handling"},
        })
        self.assertEqual(paid.target_situacao_pedido_id, PAID)
        shipped = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "ready_to_ship", "substatus": "in_transit"},
        })
        self.assertEqual(shipped.target_situacao_pedido_id, SHIPPED)

    def test_case_04_ready_to_ship_is_not_label_issued(self):
        # `ready_to_ship` do Meli e "aguardando envio". So a Shopee tem um sinal
        # real de documentacao emitida (PROCESSED).
        result = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "ready_to_ship"},
        })
        self.assertEqual(result.lifecycle_stage, "paid_preparation")
        self.assertEqual(result.target_situacao_pedido_id, PAID)

    def test_case_05_rejected_attempt_beside_approved(self):
        result = self._meli({
            "order": {
                "status": "paid",
                "payments": [{"status": "rejected"}, {"status": "approved"}],
            },
            "shipment": {"status": "handling"},
        })
        self.assertEqual(result.payment_status, "approved")
        self.assertEqual(result.target_situacao_pedido_id, PAID)

    def test_case_06_cancelled_label_keeps_the_sale_alive(self):
        result = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "cancelled"},
        })
        self.assertEqual(result.target_situacao_pedido_id, PAID)

    def test_case_07_cancellation_after_shipping_without_return(self):
        result = self._meli({
            "order": {"status": "cancelled", "payments": [{"status": "approved"}]},
            "shipment": {"status": "shipped"},
        })
        self.assertEqual(
            project_operational_status(SHIPPED, result.target_situacao_pedido_id),
            SHIPPED,
        )

    def test_case_08_total_refund_after_shipping_is_a_return(self):
        result = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "delivered"},
            "return": {"status_money": "refunded", "subtype": "return_total"},
        })
        self.assertEqual(result.lifecycle_stage, "returned")
        self.assertEqual(
            project_operational_status(SHIPPED, result.target_situacao_pedido_id),
            RETURNED,
        )

    def test_case_09_partial_return_preserves_delivery(self):
        result = self._meli({
            "order": {"status": "partially_refunded", "payments": [{"status": "approved"}]},
            "shipment": {"status": "delivered"},
            "return": {"status": "delivered", "subtype": "return_partial"},
        })
        self.assertEqual(result.lifecycle_stage, "partially_refunded")
        self.assertEqual(result.target_situacao_pedido_id, DELIVERED)

    def test_case_10_not_delivered_is_never_a_cancellation(self):
        result = self._meli({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "not_delivered", "substatus": "receiver_absent"},
        })
        self.assertEqual(result.target_situacao_pedido_id, SHIPPED)

    def test_total_refund_before_shipping_is_a_cancellation(self):
        result = self._meli({
            "order": {"status": "cancelled", "payments": [{"status": "refunded"}]},
            "shipment": {"status": "ready_to_ship", "substatus": "printed"},
        })
        self.assertEqual(result.target_situacao_pedido_id, CANCELLED)

    def test_chargeback_only_reverses_when_settled(self):
        pending = self._meli({
            "order": {"status": "paid", "payments": [
                {"status": "charged_back", "status_detail": "in_process"}
            ]},
            "shipment": {"status": "shipped"},
        })
        self.assertEqual(pending.target_situacao_pedido_id, SHIPPED)
        settled = self._meli({
            "order": {"status": "paid", "payments": [
                {"status": "charged_back", "status_detail": "settled"}
            ]},
            "shipment": {"status": "shipped"},
        })
        self.assertEqual(settled.target_situacao_pedido_id, RETURNED)


class BlingCases(unittest.TestCase):
    def setUp(self):
        self.lex = _offline()

    def test_case_13_atendido_is_shipped_not_delivered(self):
        result = resolve_bling(
            {"data": {"id": 991, "situacao": {"id": 9}}}, resolver=self.lex
        )
        self.assertEqual(result.lifecycle_stage, "shipped")
        self.assertEqual(result.target_situacao_pedido_id, SHIPPED)

    def test_bling_verified_is_fulfillment_ready(self):
        # Bling 24 (Verificado) equivale a documentacao conferida: fila de
        # expedicao, como o PROCESSED da Shopee.
        result = resolve_bling(
            {"data": {"id": 991, "situacao": {"id": 24}}}, resolver=self.lex
        )
        self.assertEqual(result.lifecycle_stage, "fulfillment_ready")
        self.assertEqual(result.target_situacao_pedido_id, READY)

    def test_case_14_erp_facts_never_project(self):
        result = resolve_bling(
            {"data": {"id": 991, "numero": "12345", "notaFiscal": {"id": 7}}},
            resolver=self.lex,
        )
        self.assertIsNone(result.target_situacao_pedido_id)
        self.assertEqual(result.lifecycle_stage, "unknown")

    def test_case_12_authority_by_ingest_origin_mode(self):
        # Bling nao dita ciclo de vida onde o marketplace integra direto.
        self.assertFalse(is_authoritative("marketplace_direct", "erp", "order"))
        self.assertTrue(is_authoritative("marketplace_direct", "marketplace", "order"))
        # Sem integracao direta, o ERP manda.
        self.assertTrue(is_authoritative("erp_bling", "erp", "order"))
        self.assertFalse(is_authoritative("erp_bling", "marketplace", "order"))
        self.assertTrue(is_authoritative("erp_only_dummy", "erp", "order"))
        self.assertFalse(is_authoritative("erp_only_dummy", "marketplace", "order"))
        # Identidade e fiscal nunca projetam, em modo nenhum.
        self.assertFalse(is_authoritative("erp_bling", "erp", "erp"))
        # Chat nunca altera estado.
        self.assertFalse(is_authoritative("marketplace_direct", "chat", "order"))


class OrderIndependence(unittest.TestCase):
    """Casos 16/17: o que cabe a esta camada e ser deterministica."""

    def setUp(self):
        self.lex = _offline()

    def test_same_snapshot_always_yields_the_same_decision(self):
        detail = {
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "ready_to_ship", "substatus": "in_transit"},
        }
        decisions = {
            resolve_mercadolivre(detail, resolver=self.lex).to_event()["lifecycle_stage"]
            for _ in range(5)
        }
        self.assertEqual(decisions, {"shipped"})

    def test_terminal_return_absorbs_every_later_target(self):
        for target in (PENDING, PAID, READY, SHIPPED, DELIVERED, CANCELLED, None):
            with self.subTest(target=target):
                self.assertEqual(project_operational_status(RETURNED, target), RETURNED)

    def test_produced_is_unreachable_from_outside(self):
        for previous in (None, PENDING, PAID, PRODUCED, READY, SHIPPED):
            with self.subTest(previous=previous):
                self.assertEqual(
                    project_operational_status(previous, PRODUCED), previous
                )

    def test_label_issued_never_regresses_internal_production(self):
        # 3 e 4 sao eixos concorrentes: producao interna vs. logistica do
        # provider. Etiqueta emitida nao desfaz producao.
        self.assertEqual(project_operational_status(PRODUCED, READY), PRODUCED)
        self.assertEqual(project_operational_status(PAID, READY), READY)
        self.assertEqual(project_operational_status(SHIPPED, READY), SHIPPED)


if __name__ == "__main__":
    unittest.main()
