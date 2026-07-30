import json
import unittest
from pathlib import Path
from unittest.mock import patch

from nistiprint_shared.services.marketplace_adapters import (
    MercadoLivreAdapter,
    ShopeeAdapter,
)
from nistiprint_shared.services.marketplace_lifecycle_service import (
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_RETURNED,
    STATUS_SHIPPED,
    resolve_shopee,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "marketplace"


class TestMercadoLivreAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = MercadoLivreAdapter()
        self.integration = {"access_token": "redacted"}

    def test_cashback_reference_never_becomes_order(self):
        ref = self.adapter.parse_webhook({
            "topic": "payments",
            "resource": "/collections/169100777527",
            "user_id": 1,
        }).primary_resource
        payment = {
            "id": 169100777527,
            "external_reference": "cashback_2963193951",
            "order": {"id": 47553648138, "type": "merchant_order"},
        }
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_collection",
            return_value=payment,
        ), patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_order_detail"
        ) as get_order:
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.status, "unresolved_payment")
        self.assertEqual(result.resolved_order_ids, ())
        get_order.assert_not_called()

    def test_valid_collection_resolves_typed_meli_order(self):
        payment = json.loads(
            (FIXTURES / "mercadolivre_collection_anonymized.json").read_text()
        )
        ref = self.adapter.parse_webhook({
            "topic": "payments",
            "resource": f"/collections/{payment['id']}",
            "user_id": 1,
        }).primary_resource
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_collection",
            return_value=payment,
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.resolved_order_ids, ("2000017477489446",))

    def test_shipment_pack_resolves_every_order(self):
        pack = json.loads(
            (FIXTURES / "mercadolivre_pack_anonymized.json").read_text()
        )
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
                return_value={"id": 5555555555, "pack_id": pack["id"]},
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_pack",
                return_value=pack,
            ),
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(
            result.resolved_order_ids,
            ("2000017477489446", "2000017477489555"),
        )

    def test_simple_shipment_resolves_direct_order(self):
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
            return_value={"id": 5555555555, "order_id": 2000017477489446},
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.resolved_order_ids, ("2000017477489446",))

    def test_shipment_without_relation_is_terminal(self):
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
            return_value={"id": 5555555555, "status": "handling"},
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.error_type, "shipment_without_order_reference")
        self.assertFalse(result.retryable)

    def test_topic_resource_mismatch_is_terminal_without_call(self):
        result = self.adapter.parse_webhook({
            "topic": "orders_v2",
            "resource": "/collections/169100777527",
            "user_id": 1,
        })
        self.assertEqual(result.status, "topic_resource_mismatch")
        self.assertFalse(result.retryable)
        self.assertEqual(result.resources, ())

    def test_malformed_id_is_rejected(self):
        result = self.adapter.parse_webhook({
            "topic": "orders_v2",
            "resource": "/orders/cashback_2963193951",
            "user_id": 1,
        })
        self.assertEqual(result.error_type, "invalid_provider_resource_id")


class TestShopeeAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ShopeeAdapter()

    def test_codes_are_routed_explicitly(self):
        self.assertEqual(
            self.adapter.parse_webhook({"code": 10, "shop_id": 1}).classification,
            "chat",
        )
        self.assertEqual(
            self.adapter.parse_webhook({"code": 0}).classification,
            "verification",
        )
        self.assertEqual(
            self.adapter.parse_webhook({"code": 999}).classification,
            "unsupported",
        )

    def test_order_push_uses_documented_identity(self):
        payload = json.loads(
            (FIXTURES / "shopee_order_push_anonymized.json").read_text()
        )
        result = self.adapter.parse_webhook(payload)
        self.assertEqual(result.resolved_order_ids, ("260730ABC123XYZ",))
        self.assertEqual(result.primary_resource.account_id, "987654321")

    def test_all_observed_states_are_canonical(self):
        expected = {
            "UNPAID": STATUS_PENDING,
            "READY_TO_SHIP": STATUS_PAID,
            "PROCESSED": STATUS_READY,
            "SHIPPED": STATUS_SHIPPED,
            "TO_CONFIRM_RECEIVE": STATUS_SHIPPED,
            "COMPLETED": STATUS_DELIVERED,
            "IN_CANCEL": STATUS_CANCELLED,
            "CANCELLED": STATUS_CANCELLED,
            "TO_RETURN": STATUS_RETURNED,
        }
        for status, target in expected.items():
            with self.subTest(status=status):
                self.assertEqual(
                    resolve_shopee({"order_status": status}).target_situacao_pedido_id,
                    target,
                )

    def test_arbitrary_text_does_not_infer_return(self):
        result = resolve_shopee({
            "order_status": "COMPLETED",
            "raw": {"message_to_seller": "please return my call"},
        })
        self.assertEqual(result.target_situacao_pedido_id, STATUS_DELIVERED)


if __name__ == "__main__":
    unittest.main()
