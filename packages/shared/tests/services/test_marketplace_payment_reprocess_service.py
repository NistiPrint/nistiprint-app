import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_payment_reprocess_service import (
    MarketplacePaymentReprocessService,
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


if __name__ == "__main__":
    unittest.main()
