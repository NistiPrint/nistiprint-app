import json
import unittest
from pathlib import Path
from unittest.mock import patch

from nistiprint_shared.mappers.order_mappers import ShopeeMapper
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

    def test_new_format_shipment_resolves_order_via_items(self):
        """x-format-new nao traz order_id/pack_id: cai em /shipments/{id}/items."""
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
                return_value={
                    "id": 5555555555,
                    "status": "shipped",
                    "substatus": "",
                    "external_reference": None,
                    "logistic": {"mode": "me2", "type": "xd_drop_off"},
                },
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment_items",
                return_value={"items": [
                    {"item_id": "MLB1", "order_id": "2000017477489446", "quantity": 1},
                    {"item_id": "MLB2", "order_id": "2000017477489446", "quantity": 2},
                ]},
            ),
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.resolved_order_ids, ("2000017477489446",))

    def test_new_format_shipment_items_resolves_pack_orders(self):
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
                return_value={"id": 5555555555, "status": "ready_to_ship"},
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment_items",
                return_value={"items": [
                    {"item_id": "MLB1", "order_id": "2000017477489446"},
                    {"item_id": "MLB2", "order_id": "2000017477489555"},
                ]},
            ),
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(
            result.resolved_order_ids,
            ("2000017477489446", "2000017477489555"),
        )

    def test_shipment_without_relation_is_terminal(self):
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
                return_value={"id": 5555555555, "status": "handling"},
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment_items",
                return_value={"items": []},
            ),
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.error_type, "shipment_without_order_reference")
        self.assertFalse(result.retryable)

    def test_shipment_items_provider_failure_is_surfaced(self):
        ref = self.adapter.parse_webhook({
            "topic": "shipments",
            "resource": "/shipments/5555555555",
            "user_id": 1,
        }).primary_resource
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment",
                return_value={"id": 5555555555, "status": "handling"},
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment_items",
                return_value={
                    "error": "Erro na API Mercado Livre: 429",
                    "error_type": "provider_rate_limited",
                    "retryable": True,
                },
            ),
        ):
            result = self.adapter.resolve_order_ids(ref, self.integration)
        self.assertEqual(result.error_type, "provider_rate_limited")
        self.assertTrue(result.retryable)

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

    def test_post_purchase_claim_resolves_typed_order_and_return(self):
        parsed = self.adapter.parse_webhook({
            "topic": "post_purchase",
            "actions": ["claims_actions"],
            "resource": "post-purchase/v1/claims/5298178312",
            "user_id": 1,
        })
        self.assertEqual(parsed.primary_resource.resource_type, "claim")
        claim = {
            "id": 5298178312,
            "resource": "order",
            "resource_id": 2000017477489446,
            "related_entities": ["return"],
        }
        return_detail = {
            "id": 57341011,
            "resource_type": "order",
            "resource_id": 2000017477489446,
            "subtype": "return_total",
            "status": "delivered",
        }
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_claim",
                return_value=claim,
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_claim_returns",
                return_value=return_detail,
            ),
        ):
            resolved = self.adapter.resolve_order_ids(
                parsed.primary_resource, self.integration
            )
        self.assertEqual(resolved.resolved_order_ids, ("2000017477489446",))
        self.assertEqual(resolved.context["return"]["status"], "delivered")

    def test_open_claim_without_return_does_not_infer_return(self):
        parsed = self.adapter.parse_webhook({
            "topic": "post_purchase",
            "actions": ["claims"],
            "resource": "/post-purchase/v1/claims/5298178312",
            "user_id": 1,
        })
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_claim",
            return_value={
                "id": 5298178312,
                "resource": "order",
                "resource_id": 2000017477489446,
                "status": "opened",
                "related_entities": [],
            },
        ):
            resolved = self.adapter.resolve_order_ids(
                parsed.primary_resource, self.integration
            )
        self.assertEqual(resolved.resolved_order_ids, ("2000017477489446",))
        self.assertNotIn("return", resolved.context)
    def test_order_snapshot_preserves_validated_identity_for_mirror(self):
        with (
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_order_detail",
                return_value={"id": 2000017477489446, "status": "paid"},
            ),
            patch(
                "nistiprint_shared.services.marketplace_adapters.meli_driver.get_shipment"
            ) as get_shipment,
        ):
            snapshot = self.adapter.fetch_order_snapshot(
                "2000017477489446", self.integration
            )

        self.assertEqual(snapshot.order_id, "2000017477489446")
        self.assertEqual(snapshot.raw["external_id"], "2000017477489446")
        self.assertEqual(snapshot.raw["order"]["id"], 2000017477489446)
        get_shipment.assert_not_called()

    def test_order_snapshot_rejects_provider_identity_mismatch(self):
        with patch(
            "nistiprint_shared.services.marketplace_adapters.meli_driver.get_order_detail",
            return_value={"id": 2000017477489555, "status": "paid"},
        ):
            result = self.adapter.fetch_order_snapshot(
                "2000017477489446", self.integration
            )

        self.assertEqual(result["error_type"], "provider_identity_mismatch")
        self.assertFalse(result["retryable"])


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
            # PROCESSED = documentacao emitida pela Shopee -> fila de expedicao.
            "PROCESSED": STATUS_READY,
            "SHIPPED": STATUS_SHIPPED,
            "TO_CONFIRM_RECEIVE": STATUS_SHIPPED,
            "COMPLETED": STATUS_DELIVERED,
            # Solicitacao de cancelamento sujeita a recusa: nao projeta.
            "IN_CANCEL": None,
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


    def test_shopee_mapper_preserves_message_to_seller(self):
        mapped = ShopeeMapper.map({
            "order_sn": "SN123",
            "message_to_seller": "Nome: Maria",
            "buyer_username": "maria123",
            "recipient_address": {},
            "item_list": [],
        })

        self.assertEqual(mapped["message_to_seller"], "Nome: Maria")

if __name__ == "__main__":
    unittest.main()
