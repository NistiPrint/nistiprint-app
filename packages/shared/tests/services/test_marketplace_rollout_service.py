import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_contracts import CanonicalOrderSnapshot
from nistiprint_shared.services.marketplace_lifecycle_service import STATUS_RETURNED
from nistiprint_shared.services.marketplace_rollout_service import (
    MarketplaceRolloutService,
)


class TestMarketplaceRolloutService(unittest.TestCase):
    def setUp(self):
        self.service = MarketplaceRolloutService()

    def test_default_mode_is_shadow(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.service.mode_for("shopee", {"id": 12}), "shadow")

    def test_shadow_compares_same_snapshot_and_keeps_legacy_authority(self):
        snapshot = CanonicalOrderSnapshot(
            provider="shopee",
            order_id="260730ABC123",
            order_status="TO_RETURN",
            raw={"order_status": "TO_RETURN"},
        )
        decision = self.service.normalize(
            "shopee",
            snapshot,
            {"code": 3},
            {"id": 12, "config": {"marketplace_adapter_mode": "shadow"}},
        )
        self.assertEqual(decision.mode, "shadow")
        self.assertTrue(decision.diverged)
        self.assertIsNone(decision.lifecycle.target_situacao_pedido_id)
        self.assertEqual(
            decision.active_lifecycle.target_situacao_pedido_id,
            STATUS_RETURNED,
        )

    def test_active_integration_allowlist_is_progressive(self):
        config = {
            "marketplace_adapter_mode": "active",
            "marketplace_adapter_rollout": {
                "shopee": {"active_integration_ids": [12]}
            },
        }
        self.assertEqual(self.service.mode_for("shopee", {"id": 12, "config": config}), "active")
        self.assertEqual(self.service.mode_for("shopee", {"id": 13, "config": config}), "shadow")

    def test_rollback_flag_returns_legacy(self):
        with patch.dict(
            "os.environ",
            {
                "MARKETPLACE_ADAPTER_MODE_MERCADOLIVRE": "active",
                "MARKETPLACE_ADAPTER_ROLLBACK_MERCADOLIVRE": "true",
                "MARKETPLACE_ADAPTER_ROLLBACK_UNTIL_MERCADOLIVRE": "2099-01-01T00:00:00Z",
            },
            clear=False,
        ):
            self.assertEqual(self.service.mode_for("mercadolivre", {"id": 12}), "legacy")


if __name__ == "__main__":
    unittest.main()
