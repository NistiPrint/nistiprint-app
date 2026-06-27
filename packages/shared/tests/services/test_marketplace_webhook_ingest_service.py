
import unittest
from unittest.mock import patch

from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    MarketplaceWebhookIngestService,
    _extract_resource_id,
)
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver


class TestMarketplaceWebhookIngestService(unittest.TestCase):
    def test_extract_resource_id_ignores_endpoint_suffix(self):
        self.assertEqual(
            _extract_resource_id('/shipments/47344057080/assignment/v1', '/shipments/'),
            '47344057080',
        )
        self.assertEqual(
            _extract_resource_id('/payments/998877/details', '/payments/'),
            '998877',
        )

    @patch('nistiprint_shared.services.platform_drivers.mercadolivre.requests.get')
    def test_ml_driver_sanitizes_shipment_id_before_building_url(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = '{}'
        mock_get.return_value.json.return_value = {'id': 47344057080}

        result = meli_driver.get_shipment(
            {'access_token': 'token'},
            '47344057080/assignment/v1',
        )

        self.assertEqual(result['id'], 47344057080)
        self.assertEqual(
            mock_get.call_args.args[0],
            'https://api.mercadolibre.com/shipments/47344057080',
        )

    def test_shopee_webhook_persists_without_bling_materialization(self):
        service = MarketplaceWebhookIngestService()
        resolved_status = unittest.mock.MagicMock(
            internal_situacao_pedido_id=4,
            external_status_id='PROCESSED',
        )

        with patch.object(service, '_resolve_marketplace_integration', return_value=({'id': 12}, None)), \
             patch.object(service, '_find_direct_ingest_link', return_value={'channel_id': 22, 'process_webhooks': True, 'ingest_origin_mode': 'marketplace_direct'}), \
             patch.object(service, '_fetch_shopee_detail', return_value={'order_status': 'PROCESSED', 'external_id': 'SN123'}), \
             patch.object(service, '_upsert_shopee_mirror', return_value=44), \
             patch.object(service, '_upsert_pedido_status', return_value=55) as upsert_status, \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_status_service.resolve_shopee', return_value=resolved_status):
            result = service._process_shopee({'order_sn': 'SN123', 'shop_id': 'SHOP1'}, correlation_id='cid')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['pedido_id'], 55)
        upsert_status.assert_called_once()
        self.assertIsNone(upsert_status.call_args.kwargs['bling_integration_id'])

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

    def test_shopee_without_bling_order_is_still_successful(self):
        service = MarketplaceWebhookIngestService()
        resolved_status = unittest.mock.MagicMock(
            internal_situacao_pedido_id=4,
            external_status_id='PROCESSED',
        )

        with patch.object(service, '_resolve_marketplace_integration', return_value=({'id': 12}, None)), \
             patch.object(service, '_find_direct_ingest_link', return_value={'channel_id': 22, 'process_webhooks': True, 'ingest_origin_mode': 'marketplace_direct'}), \
             patch.object(service, '_fetch_shopee_detail', return_value={'order_status': 'PROCESSED', 'external_id': 'SN123'}), \
             patch.object(service, '_upsert_shopee_mirror', return_value=44), \
             patch.object(service, '_upsert_pedido_status', return_value=55), \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_status_service.resolve_shopee', return_value=resolved_status):
            result = service._process_shopee({'order_sn': 'SN123', 'shop_id': 'SHOP1'}, correlation_id='cid')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['pedido_id'], 55)

    def test_upsert_pedido_status_does_not_require_bling_order_number(self):
        service = MarketplaceWebhookIngestService()

        with patch.object(service, '_lookup_bling_order') as lookup, \
             patch.object(service, '_normalize_shopee_items', return_value=[]), \
             patch.object(service, '_customer_name', return_value='Cliente'), \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.logistica_coleta_service.calcular_data_coleta', return_value={}), \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_repository.upsert', return_value=55), \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_repository.defer_unresolved_erp_order') as defer, \
             patch('nistiprint_shared.services.marketplace_webhook_ingest_service.persist_classification_from_payload'):
            pedido_id = service._upsert_pedido_status(
                source='shopee', external_order_id='SN123',
                marketplace_integration_id=12, bling_integration_id=None,
                bling_loja_id=None, channel_id=22, situacao_pedido_id=4,
                status_original='PROCESSED', mirror_fields={'pedido_shopee_id': 44},
                raw_customer={'name': 'Cliente'}, total=10, currency='BRL',
                data_venda='2026-06-23T10:00:00+00:00', details={},
            )

        self.assertEqual(pedido_id, 55)
        lookup.assert_not_called()
        defer.assert_called_once()


    def test_materialization_error_preserves_retry_after_for_rate_limit(self):
        service = MarketplaceWebhookIngestService()

        result = service._bling_materialization_error_result(
            source='mercadolivre',
            external_order_id='26174897235',
            marketplace_integration_id=12,
            result={
                'reason': 'bling_rate_limited',
                'message': 'Limite de requisicoes do Bling atingido',
                'retry_after': 2.5,
            },
        )

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'bling_rate_limited')
        self.assertEqual(result['retry_after'], 2.5)


    def test_erp_only_webhook_is_queued_for_enrichment(self):
        service = MarketplaceWebhookIngestService()
        link = {"process_webhooks": True, "ingest_origin_mode": "erp_bling"}

        with patch.object(service, '_find_bling_links', return_value=[]),              patch(
                 "nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_repository.queue_marketplace_enrichment"
             ) as queue:
            result = service._inactive_source_result(
                "shopee", link, "SN123", {"id": 12},
                payload={"event_id": "evt-1", "order_sn": "SN123"},
            )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["event_status"], "pending_erp_order")
        queue.assert_called_once_with(
            marketplace_integration_id=12,
            marketplace_module_id="shopee",
            marketplace_order_id="SN123",
            payload={"event_id": "evt-1", "order_sn": "SN123"},
            event_type=None,
            source_event_id="evt-1",
        )

    def test_erp_only_webhook_proceeds_when_order_already_exists_in_bling(self):
        service = MarketplaceWebhookIngestService()
        link = {"process_webhooks": True, "ingest_origin_mode": "erp_bling"}

        with patch.object(service, '_find_bling_links', return_value=[{'erp_integration_id': 99}]),              patch.object(service, '_lookup_bling_order', return_value={
                 'status': 'found',
                 'bling_order_id': 987,
                 'bling_order_number': '466320',
             }),              patch(
                 "nistiprint_shared.services.marketplace_webhook_ingest_service.canonical_order_repository.queue_marketplace_enrichment"
             ) as queue:
            result = service._inactive_source_result(
                "shopee", link, "SN123", {"id": 12},
                payload={"event_id": "evt-1", "order_sn": "SN123"},
            )

        self.assertIsNone(result)
        queue.assert_not_called()



if __name__ == "__main__":
    unittest.main()


