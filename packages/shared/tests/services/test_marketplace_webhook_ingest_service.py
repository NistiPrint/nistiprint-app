import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
)


class TestMarketplaceWebhookIngestService(unittest.TestCase):
    def test_shopee_materialized_order_syncs_marketplace_status(self):
        service = MarketplaceWebhookIngestService()
        resolved_status = unittest.mock.MagicMock(
            internal_situacao_pedido_id=4,
            external_status_id='PROCESSED',
        )

        with patch.object(service, '_resolve_marketplace_integration', return_value=({'id': 12}, None)), \
             patch.object(service, '_find_direct_ingest_link', return_value={'channel_id': 22, 'process_webhooks': True, 'ingest_origin_mode': 'marketplace_direct'}), \
             patch.object(service, '_find_default_nfe_link', return_value={'erp_integration_id': 99, 'erp_store_id': '54533'}), \
             patch.object(service, '_fetch_shopee_detail', return_value={'order_status': 'PROCESSED', 'external_id': 'SN123'}), \
             patch.object(service, '_upsert_shopee_mirror', return_value=44), \
             patch.object(service, '_try_materialize_from_bling', return_value={'status': 'success', 'pedido_id': 55, 'pedido_bling_id': 66}), \
             patch.object(service, '_update_materialized_pedido_status') as update_status, \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_status_service.resolve_shopee', return_value=resolved_status):
            result = service._process_shopee({'order_sn': 'SN123', 'shop_id': 'SHOP1'}, correlation_id='cid')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['pedido_id'], 55)
        self.assertEqual(result['internal_situacao_pedido_id'], 4)
        update_status.assert_called_once_with(
            pedido_id=55,
            situacao_pedido_id=4,
            status_original='PROCESSED',
            source='shopee',
        )

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

    def test_shopee_without_bling_order_returns_retryable_error(self):
        service = MarketplaceWebhookIngestService()
        resolved_status = unittest.mock.MagicMock(
            internal_situacao_pedido_id=4,
            external_status_id='PROCESSED',
        )

        with patch.object(service, '_resolve_marketplace_integration', return_value=({'id': 12}, None)), \
             patch.object(service, '_find_direct_ingest_link', return_value={'channel_id': 22, 'process_webhooks': True, 'ingest_origin_mode': 'marketplace_direct'}), \
             patch.object(service, '_find_default_nfe_link', return_value={'erp_integration_id': 99, 'erp_store_id': '54533'}), \
             patch.object(service, '_fetch_shopee_detail', return_value={'order_status': 'PROCESSED', 'external_id': 'SN123'}), \
             patch.object(service, '_upsert_shopee_mirror', return_value=44), \
             patch.object(service, '_try_materialize_from_bling', return_value={'status': 'not_found', 'reason': 'bling_order_not_found'}), \
             patch.object(service, '_upsert_pedido_status') as upsert_pedido_status, \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_status_service.resolve_shopee', return_value=resolved_status):
            result = service._process_shopee({'order_sn': 'SN123', 'shop_id': 'SHOP1'}, correlation_id='cid')

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'bling_order_not_found')
        self.assertEqual(result['event_status'], 'bling_order_not_found')
        upsert_pedido_status.assert_not_called()

    def test_upsert_pedido_status_requires_bling_order_number(self):
        service = MarketplaceWebhookIngestService()

        with patch.object(service, '_lookup_bling_order', return_value={'status': 'not_found'}):
            with self.assertRaisesRegex(RuntimeError, 'sem numero_pedido resolvido no Bling'):
                service._upsert_pedido_status(
                    source='shopee',
                    external_order_id='SN123',
                    marketplace_integration_id=12,
                    bling_integration_id=99,
                    bling_loja_id='54533',
                    channel_id=22,
                    situacao_pedido_id=4,
                    status_original='PROCESSED',
                    mirror_fields={'pedido_shopee_id': 44},
                    raw_customer={'name': 'Cliente'},
                    total=10,
                    currency='BRL',
                    data_venda='2026-06-23T10:00:00+00:00',
                    details={},
                )


if __name__ == "__main__":
    unittest.main()
