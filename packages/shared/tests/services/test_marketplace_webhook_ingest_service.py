import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
)


class TestMarketplaceWebhookIngestService(unittest.TestCase):
    def test_write_snapshot_classifies_direct_marketplace_items(self):
        service = MarketplaceWebhookIngestService()
        detail = {
            "item_list": [{
                "item_name": "Caderneta de Vacinacao Personalizado C/ Nome",
                "model_sku": "VACMNA_JAEN1_BBB",
                "model_quantity_purchased": 1,
                "model_discounted_price": 10,
            }],
            "buyer_username": "cliente",
        }

        with patch(
            "nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_snapshot_service.upsert_snapshot"
        ) as snapshot_mock:
            with patch(
                "nistiprint_shared.services.marketplace_webhook_ingest_service.persist_classification_from_payload"
            ) as persist_mock:
                service._write_snapshot_for_marketplace(
                    source="shopee",
                    pedido_id=26893,
                    external_order_id="260618E2UXVM97",
                    marketplace_integration_id=12,
                    bling_integration_id=99,
                    customer={"name": "Cliente"},
                    total=10,
                    currency="BRL",
                    details=detail,
                    mirror_fields={},
                )

        snapshot_mock.assert_called_once()
        persist_mock.assert_called_once()
        payload_arg = persist_mock.call_args.args[0]
        self.assertEqual(payload_arg["numeroLoja"], "260618E2UXVM97")
        self.assertEqual(payload_arg["itens"][0]["name"], "Caderneta de Vacinacao Personalizado C/ Nome")


if __name__ == "__main__":
    unittest.main()
