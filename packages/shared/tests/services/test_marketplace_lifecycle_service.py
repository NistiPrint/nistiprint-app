import unittest

from nistiprint_shared.services.marketplace_lifecycle_service import (
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_READY,
    STATUS_RETURNED,
    STATUS_SHIPPED,
    project_operational_status,
    resolve_mercadolivre,
    resolve_shopee,
)


class TestMarketplaceLifecycleService(unittest.TestCase):
    def test_meli_approved_payment_wins_over_rejected_attempt(self):
        result = resolve_mercadolivre({
            "order": {
                "status": "paid",
                "payments": [{"status": "rejected"}, {"status": "approved"}],
            },
            "shipment": {"status": "handling"},
        })
        self.assertEqual(result.payment_status, "approved")
        self.assertEqual(result.target_situacao_pedido_id, STATUS_PAID)

    def test_meli_ready_to_ship_is_documentation_ready(self):
        result = resolve_mercadolivre({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "ready_to_ship"},
        })
        self.assertEqual(result.lifecycle_stage, "documentation_ready")
        self.assertEqual(result.target_situacao_pedido_id, STATUS_READY)

    def test_meli_cancel_before_shipping_is_cancelled(self):
        result = resolve_mercadolivre({
            "order": {"status": "cancelled", "payments": []},
            "shipment": {"status": "pending"},
        })
        self.assertEqual(result.target_situacao_pedido_id, STATUS_CANCELLED)

    def test_meli_cancel_after_shipping_is_returned(self):
        result = resolve_mercadolivre({
            "order": {"status": "cancelled", "payments": [{"status": "refunded"}]},
            "shipment": {"status": "not_delivered", "substatus": "returning_to_sender"},
        })
        self.assertEqual(result.lifecycle_stage, "returned")
        self.assertEqual(result.target_situacao_pedido_id, STATUS_RETURNED)

    def test_meli_not_delivered_without_return_is_shipping_exception(self):
        result = resolve_mercadolivre({
            "order": {"status": "paid", "payments": [{"status": "approved"}]},
            "shipment": {"status": "not_delivered", "substatus": "receiver_absent"},
        })
        self.assertEqual(result.lifecycle_stage, "shipping_exception")
        self.assertEqual(result.target_situacao_pedido_id, STATUS_SHIPPED)

    def test_shopee_sequence_mapping(self):
        expected = {
            "READY_TO_SHIP": STATUS_PAID,
            "PROCESSED": STATUS_READY,
            "SHIPPED": STATUS_SHIPPED,
            "TO_CONFIRM_RECEIVE": STATUS_SHIPPED,
            "COMPLETED": STATUS_DELIVERED,
            "CANCELLED": STATUS_CANCELLED,
        }
        for status, target in expected.items():
            with self.subTest(status=status):
                self.assertEqual(
                    resolve_shopee({"order_status": status}).target_situacao_pedido_id,
                    target,
                )

    def test_shopee_refund_event_is_returned_even_after_completion(self):
        result = resolve_shopee(
            {"order_status": "COMPLETED"},
            {"event_type": "REFUND_UPDATE", "refund_status": "approved"},
        )
        self.assertEqual(result.lifecycle_stage, "returned")
        self.assertEqual(result.target_situacao_pedido_id, STATUS_RETURNED)

    def test_projection_preserves_internal_production_from_provider_regression(self):
        self.assertEqual(project_operational_status(3, 2), 3)
        self.assertEqual(project_operational_status(3, 4), 3)
        self.assertEqual(project_operational_status(4, 2), 4)

    def test_projection_preserves_terminal_states_and_promotes_returns(self):
        self.assertEqual(project_operational_status(6, 5), 6)
        self.assertEqual(project_operational_status(8, 6), 8)
        self.assertEqual(project_operational_status(6, 7), 8)

    def test_projection_allows_complete_forward_sequence(self):
        current = None
        for target in (1, 2, 4, 5, 6):
            current = project_operational_status(current, target)
        self.assertEqual(current, 6)

    def test_provider_timestamp_prefers_latest_resource(self):
        result = resolve_mercadolivre({
            "order": {
                "status": "paid",
                "last_updated": "2026-06-26T10:00:00Z",
                "payments": [{"status": "approved"}],
            },
            "shipment": {
                "status": "shipped",
                "last_updated": "2026-06-26T11:00:00Z",
            },
        })
        self.assertEqual(result.observed_at, "2026-06-26T11:00:00Z")


if __name__ == "__main__":
    unittest.main()
