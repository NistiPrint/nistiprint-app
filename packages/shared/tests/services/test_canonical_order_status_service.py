import unittest
from unittest.mock import patch

from nistiprint_shared.services import canonical_order_status_service as status_service
from nistiprint_shared.services.order_status_lexicon import LexiconResolver


def _offline_service():
    """Servico com o lexico preso ao SEED, sem tocar no banco."""
    resolver = LexiconResolver()
    with patch.object(resolver, "_load_overrides", return_value={}):
        service = status_service.CanonicalOrderStatusService(resolver)
        resolver._overrides()
    return service


class TestCanonicalOrderStatusService(unittest.TestCase):
    def test_shopee_status_mapping(self):
        service = _offline_service()
        self.assertEqual(service.resolve_shopee("UNPAID").internal_situacao_pedido_id, 1)
        self.assertEqual(service.resolve_shopee("READY_TO_SHIP").internal_situacao_pedido_id, 2)
        # PROCESSED = documentacao emitida pela Shopee -> fila de expedicao (4).
        self.assertEqual(service.resolve_shopee("PROCESSED").internal_situacao_pedido_id, 4)
        self.assertEqual(service.resolve_shopee("SHIPPED").internal_situacao_pedido_id, 5)
        self.assertEqual(service.resolve_shopee("COMPLETED").internal_situacao_pedido_id, 6)
        self.assertEqual(service.resolve_shopee("CANCELLED").internal_situacao_pedido_id, 7)

    def test_shopee_in_cancel_does_not_project(self):
        # Cancelamento na Shopee e solicitacao sujeita a recusa: projetar 7 aqui
        # exigiria regredir de estado terminal quando a recusa chegasse.
        resolved = _offline_service().resolve_shopee("IN_CANCEL")
        self.assertIsNone(resolved.internal_situacao_pedido_id)
        self.assertEqual(resolved.lifecycle_stage, "cancellation_pending")

    def test_mercadolivre_shipping_precedence_over_payment(self):
        resolved = _offline_service().resolve_mercadolivre(
            payment_status="approved", shipping_status="delivered",
        )
        self.assertEqual(resolved.internal_situacao_pedido_id, 6)
        self.assertEqual(resolved.status_domain, "shipping")
        self.assertEqual(resolved.external_status_id, "delivered")

    def test_mercadolivre_ready_to_ship_is_still_in_progress(self):
        resolved = _offline_service().resolve_mercadolivre(
            payment_status="approved", shipping_status="ready_to_ship",
        )
        self.assertEqual(resolved.internal_situacao_pedido_id, 2)
        self.assertEqual(resolved.lifecycle_stage, "paid_preparation")

    def test_mercadolivre_refund_outranks_delivery(self):
        resolved = _offline_service().resolve_mercadolivre(
            payment_status="refunded", shipping_status="delivered",
        )
        self.assertEqual(resolved.internal_situacao_pedido_id, 8)
        self.assertEqual(resolved.status_domain, "payment")

    def test_unknown_status_is_reported_not_guessed(self):
        resolved = _offline_service().resolve("shopee", "SOMETHING_NEW")
        self.assertIsNone(resolved.internal_situacao_pedido_id)
        self.assertEqual(resolved.source, "unmapped")

    def test_database_mapping_overrides_seed(self):
        resolver = LexiconResolver()
        rows = [{
            "module_id": "shopee",
            "integration_id": None,
            "status_domain": "order",
            "external_status_id": "PROCESSED",
            "lifecycle_stage": "shipped",
        }]
        with patch.object(resolver, "_load_overrides", wraps=lambda: {
            ("shopee", "order", "PROCESSED"): _entry_from(rows[0]),
        }):
            service = status_service.CanonicalOrderStatusService(resolver)
            resolved = service.resolve_shopee("PROCESSED")
        self.assertEqual(resolved.internal_situacao_pedido_id, 5)
        self.assertEqual(resolved.source, "db")


def _entry_from(row):
    from nistiprint_shared.services.order_status_lexicon import LexiconEntry

    return LexiconEntry(
        row["module_id"], row["status_domain"], row["external_status_id"],
        row["lifecycle_stage"], source="db",
    )


if __name__ == "__main__":
    unittest.main()
