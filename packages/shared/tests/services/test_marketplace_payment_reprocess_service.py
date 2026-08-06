import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_payment_reprocess_service import (
    MarketplacePaymentReprocessService,
    SHIPMENT_RESOURCE_TYPES,
    _resource_type,
    marketplace_shipment_reprocess_service,
)


class TestMarketplacePaymentReprocessService(unittest.TestCase):
    def test_dry_run_never_publishes_or_changes_orders(self):
        service = MarketplacePaymentReprocessService()
        candidates = [{
            "id": 36806,
            "provider_resource_type": "collection",
            "provider_resource_id": "169100777527",
            "last_status": "manual_intervention",
            "last_error_type": "provider_parameter_error",
            "raw_payload": {
                "topic": "payments",
                "resource": "/collections/169100777527",
            },
        }]
        with (
            patch.object(service, "list_candidates", return_value=candidates),
            patch(
                "nistiprint_shared.services.marketplace_payment_reprocess_service.publish_envelope"
            ) as publish,
        ):
            result = service.reprocess(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["candidate_count"], 1)
        publish.assert_not_called()


class TestMarketplaceShipmentReprocessService(unittest.TestCase):
    def test_service_targets_shipments_topic(self):
        service = marketplace_shipment_reprocess_service
        self.assertEqual(service.topic, "shipments")
        self.assertEqual(service.resource_types, set(SHIPMENT_RESOURCE_TYPES))
        self.assertEqual(service.label, "shipment")

    def test_resource_type_falls_back_to_resource_prefix(self):
        row = {"provider_resource_type": None, "provider_resource": "/shipments/47703541720"}
        self.assertEqual(_resource_type(row, SHIPMENT_RESOURCE_TYPES), "shipment")

    def test_payment_event_is_not_a_shipment_candidate(self):
        row = {"provider_resource_type": "collection", "provider_resource": "/collections/1"}
        self.assertIsNone(_resource_type(row, SHIPMENT_RESOURCE_TYPES))

    def test_dry_run_lists_terminal_shipment_without_publishing(self):
        service = marketplace_shipment_reprocess_service
        candidates = [{
            "id": 60713,
            "provider_resource_type": "shipment",
            "provider_resource": "/shipments/47703541720",
            "provider_resource_id": "47703541720",
            "last_status": "failed_terminal",
            "last_error_type": "shipment_without_order_reference",
            "raw_payload": {
                "topic": "shipments",
                "resource": "/shipments/47703541720",
            },
        }]
        with (
            patch.object(service, "list_candidates", return_value=candidates),
            patch(
                "nistiprint_shared.services.marketplace_payment_reprocess_service.publish_envelope"
            ) as publish,
        ):
            result = service.reprocess(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["resource_type"], "shipment")
        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
