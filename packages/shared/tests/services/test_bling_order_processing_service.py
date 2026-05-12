import json
import unittest
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import bling_order_processing_service as bos
from nistiprint_shared.services import pedidos_bling_import_service as import_service


class TestBlingOrderProcessingServiceHelpers(unittest.TestCase):
    def test_resolve_bling_instance_prefers_cached_company_id_alias(self):
        payload = {'id': 999}

        with patch.object(
            bos.integration_resolution_service,
            'resolve_bling_by_company_id',
            return_value={'id': 55, 'config': {'company_ids': ['abc']}},
        ) as cached_lookup, \
             patch.object(bos.supabase_db, 'rpc') as rpc_mock:
            result = bos._resolve_bling_instance(payload, hint=None, company_id='abc')

        self.assertEqual(result['id'], 55)
        cached_lookup.assert_called_once_with('abc')
        rpc_mock.assert_not_called()

    def test_resolve_marketplace_instance_prefers_cached_shop_alias(self):
        with patch.object(
            bos.integration_resolution_service,
            'resolve_marketplace_by_shop_id',
            return_value={'id': 77, 'module_id': 'shopee', 'plataforma_slug': 'shopee'},
        ) as cached_lookup, \
             patch.object(bos.supabase_db, 'rpc') as rpc_mock:
            result = bos._resolve_marketplace_instance('204047801', bling_integration_id=12)

        self.assertEqual(result['id'], 77)
        cached_lookup.assert_called_once_with('204047801', bling_integration_id=12)
        rpc_mock.assert_not_called()

    @patch('nistiprint_shared.services.bling.bling_client.BlingClient')
    def test_fetch_bling_order_detail_uses_bling_client(self, bling_client_cls):
        bling_client = MagicMock()
        bling_client.get_order.return_value = {'id': 123, 'contato': {'nome': 'Cliente'}}
        bling_client_cls.create_client_for_integration_id.return_value = bling_client

        detalhe = bos._fetch_bling_order_detail({'id': 77}, 123)

        self.assertEqual(detalhe, {'id': 123, 'contato': {'nome': 'Cliente'}})
        bling_client_cls.create_client_for_integration_id.assert_called_once_with(77)
        bling_client.get_order.assert_called_once_with(123)

    def test_process_webhook_raises_when_detail_is_missing(self):
        payload = {'id': 999, 'numero': '1', 'numeroLoja': 'ABC'}

        with patch.object(bos, '_resolve_bling_instance', return_value={'id': 12, 'config': {}}), \
             patch.object(bos, '_fetch_bling_order_detail', side_effect=bos.BlingDetailUnavailableError('detalhe ausente')):
            with self.assertRaises(bos.BlingDetailUnavailableError):
                bos.process_webhook(payload)

    def test_resolve_shipping_carrier_uses_fresh_shopee_data(self):
        shopee_data = {
            'shipping_carrier': 'Entrega Rapida Shopee',
            'package_list': [
                {'shipping_carrier': 'Fallback Package'}
            ],
        }

        carrier = bos._resolve_shipping_carrier(shopee_data, '2511000001')

        self.assertEqual(carrier, 'Entrega Rapida Shopee')

    def test_resolve_shipping_carrier_falls_back_to_saved_row(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                'shipping_carrier': None,
                'package_list': [
                    {'shipping_carrier': 'Entrega Rapida'}
                ],
            }
        ]

        with patch.object(bos.supabase_db, 'table', return_value=table):
            carrier = bos._resolve_shipping_carrier(None, '2511000002')

        self.assertEqual(carrier, 'Entrega Rapida')

    def test_classify_flex_accepts_case_and_accent_insensitive_entrega_rapida(self):
        result = bos._classify_flex(
            {'shipping_carrier': 'ENTREGA RÁPIDA SPX'},
            '2511000004',
            'shopee',
        )

        self.assertTrue(result.is_flex)
        self.assertEqual(result.modalidade, 'FLEX')

    def test_classify_flex_requires_shopee(self):
        result = bos._classify_flex(
            {'shipping_carrier': 'entrega rapida'},
            '2511000005',
            'mercadolivre',
        )

        self.assertFalse(result.is_flex)
        self.assertEqual(result.modalidade, 'STANDARD')

    def test_start_correlation_id_always_uses_explicit_or_new_value(self):
        with patch.object(bos, 'generate_correlation_id', return_value='novo-cid'), \
             patch.object(bos, 'set_correlation_id') as set_correlation_id:
            correlation_id = bos._start_correlation_id()

        self.assertEqual(correlation_id, 'novo-cid')
        set_correlation_id.assert_called_once_with('novo-cid')

    def test_clean_shopee_ship_by_date_converts_unix_epoch_to_iso(self):
        result = bos._clean_shopee_ship_by_date(1778122799)

        self.assertEqual(result, '2026-05-06T23:59:59-03:00')

    def test_detect_and_mark_personalized_calls_identifier(self):
        payload = {
            'numero': '12345',
            'numeroLoja': '2511000003',
            'loja': {'id': 204047801},
            'itens': [
                {'descricao': 'Agenda Personalizada', 'produto': {'id': 101}},
            ],
        }

        with patch(
            'nistiprint_shared.services.personalized_order_identifier.personalized_order_identifier.process_order',
            return_value={'success': True, 'personalized_items': [0]},
        ) as process_order:
            bos._detect_and_mark_personalized(payload, pedido_id=99)

        process_order.assert_called_once_with(payload)

    def test_preserve_original_bling_fields_keeps_loja_id_from_original_payload(self):
        original_payload = {
            'id': 19860,
            'numero': '100',
            'numeroLoja': 'ABC123',
            'loja': {'id': 204047801},
        }
        detail_payload = {
            'id': 19860,
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        merged = bos._preserve_original_bling_fields(detail_payload, original_payload)

        self.assertEqual(merged['loja']['id'], 204047801)
        self.assertEqual(merged['numeroLoja'], 'ABC123')
        self.assertEqual(merged['numero'], '100')

    def test_upsert_pedido_bling_does_not_null_loja_id_when_missing_from_payload(self):
        payload = {
            'id': 19860,
            'numero': '100',
            'numeroLoja': 'ABC123',
            'situacao': {'id': 15},
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        table = MagicMock()
        table.upsert.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos, '_find_existing_pedido_bling_for_update', return_value=None), \
             patch.object(bos.supabase_db, 'table', return_value=table):
            pedido_bling_id = bos._upsert_pedido_bling(payload, bling_integration_id=22)

        self.assertEqual(pedido_bling_id, 321)
        upsert_data = table.upsert.call_args.args[0]
        self.assertNotIn('loja_id', upsert_data)

    def test_upsert_pedido_bling_persists_loja_id_from_bling_payload(self):
        payload = {
            'id': 19860,
            'numero': '100',
            'numeroLoja': 'ABC123',
            'loja': {'id': 204047801},
            'situacao': {'id': 15},
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        table = MagicMock()
        table.upsert.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos, '_find_existing_pedido_bling_for_update', return_value=None), \
             patch.object(bos.supabase_db, 'table', return_value=table):
            pedido_bling_id = bos._upsert_pedido_bling(payload, bling_integration_id=22)

        self.assertEqual(pedido_bling_id, 321)
        upsert_data = table.upsert.call_args.args[0]
        self.assertEqual(upsert_data['loja_id'], 204047801)

    def test_upsert_pedido_bling_updates_legacy_row_instead_of_inserting_duplicate(self):
        payload = {
            'id': 19860,
            'numero': '457127',
            'numeroLoja': '2605127CMVM5MX',
            'loja': {'id': 204047801},
            'situacao': {'id': 24},
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        select_table = MagicMock()
        select_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        select_table.select.return_value.is_.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{'id': 19860}]

        update_table = MagicMock()
        update_table.update.return_value.eq.return_value.execute.return_value.data = [{'id': 19860}]

        def side_effect(name):
            self.assertEqual(name, 'pedidos_bling')
            return side_effect.tables.pop(0)

        side_effect.tables = [select_table, select_table, update_table]

        with patch.object(bos.supabase_db, 'table', side_effect=side_effect):
            pedido_bling_id = bos._upsert_pedido_bling(payload, bling_integration_id=1)

        self.assertEqual(pedido_bling_id, 19860)
        update_data = update_table.update.call_args.args[0]
        self.assertEqual(update_data['bling_integration_id'], 1)
        self.assertEqual(update_data['loja_id'], 204047801)
        update_table.update.return_value.eq.assert_called_once_with('id', 19860)

    def test_resolve_canal_venda_id_uses_store_link_without_marketplace_installation(self):
        table = MagicMock()
        table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {'channel_id': 31}
        ]

        with patch.object(bos.supabase_db, 'table', return_value=table):
            canal_id = bos._resolve_canal_venda_id(
                marketplace_integration_id=None,
                bling_integration_id=1,
                loja_id='203792892',
            )

        self.assertEqual(canal_id, 31)

    def test_process_webhook_materializes_minimal_payload_but_returns_retryable_error(self):
        payload = {
            'id': 25794098552,
            'numero': 457226,
            'numeroLoja': '76d9a774-9f9b-426a-bae6-eb3935972cbb',
            'loja': {'id': 203792892},
            'situacao': {'id': 6},
            'total': 49.9,
        }

        with patch.object(bos, '_resolve_bling_instance', return_value={'id': 1, 'config': {}}), \
             patch.object(bos, '_fetch_bling_order_detail', side_effect=bos.BlingDetailUnavailableError('offline')), \
             patch.object(bos, '_upsert_pedido_bling', return_value=19861), \
             patch.object(bos, '_resolve_marketplace_instance', return_value=None), \
             patch.object(bos, '_resolve_canal_venda_id', return_value=31), \
             patch.object(bos, '_upsert_pedido_master', return_value=16741), \
             patch.object(bos, '_detect_and_mark_personalized'), \
             patch.object(bos, '_log_ingest'), \
             patch.object(bos.demanda_producao_service, 'create_from_order'), \
             patch.object(bos, '_write_ingest_log'), \
             patch.object(bos, '_update_webhook_event'), \
             patch.object(bos.logger, 'info'), \
             patch.object(bos.logger, 'warning'):
            result = bos.process_webhook(payload, company_id='company-1')

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'bling_detail_unavailable')
        self.assertEqual(result['pedido_id'], 16741)

    def test_enqueue_bling_order_preserves_full_order_payload(self):
        full_order = {
            'id': 19860,
            'numero': '100',
            'numeroLoja': 'ABC123',
            'loja': {'id': 204047801},
            'contato': {'nome': 'Cliente'},
        }
        redis_client = MagicMock()

        with patch.object(import_service, '_get_redis_client', return_value=redis_client):
            result = import_service._enqueue_bling_order_to_redis(
                full_order,
                {'bling_company_id': 'company-1'},
            )

        self.assertTrue(result['success'])
        queued_payload = json.loads(redis_client.rpush.call_args.args[1])
        self.assertEqual(queued_payload['data']['loja']['id'], 204047801)
        self.assertEqual(queued_payload['data']['contato']['nome'], 'Cliente')

    def test_upsert_pedido_master_does_not_overwrite_cliente_with_empty_json(self):
        payload = {
            'id': 1,
            'numero': '123',
            'numeroLoja': '456',
            'total': 10,
            'data': '2026-05-02',
            'situacao': {'id': 2},
            'contato': {},
            'itens': [],
        }

        table = MagicMock()
        table.upsert.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos, '_find_existing_pedido_master_for_update', return_value=None), \
             patch.object(bos.supabase_db, 'table', return_value=table), \
             patch.object(bos, '_resolve_situacao_interna', return_value=42), \
             patch.object(bos, '_upsert_itens_pedido'), \
             patch.object(bos.logger, 'info'):
            pedido_id = bos._upsert_pedido_master(
                payload,
                pedido_bling_id=11,
                pedido_shopee_id=None,
                bling_integration_id=22,
                marketplace_integration_id=None,
                canal_venda_id=None,
                is_flex=False,
                modalidade=None,
                shopee_data=None,
            )

        self.assertEqual(pedido_id, 321)
        insert_data = table.insert.call_args.args[0]
        self.assertNotIn('informacoes_cliente', insert_data)

    def test_upsert_pedido_master_uses_shopee_ship_by_date_for_deadline(self):
        payload = {
            'id': 1,
            'numero': '123',
            'numeroLoja': '456',
            'total': 10,
            'data': '2026-05-02',
            'situacao': {'id': 2},
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        table = MagicMock()
        table.upsert.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos, '_find_existing_pedido_master_for_update', return_value=None), \
             patch.object(bos.supabase_db, 'table', return_value=table), \
             patch.object(bos, '_resolve_situacao_interna', return_value=42), \
             patch.object(bos, '_upsert_itens_pedido'), \
             patch.object(bos.logger, 'info'):
            bos._upsert_pedido_master(
                payload,
                pedido_bling_id=11,
                pedido_shopee_id=None,
                bling_integration_id=22,
                marketplace_integration_id=None,
                canal_venda_id=None,
                is_flex=False,
                modalidade=None,
                shopee_data={'ship_by_date': 1778122799},
            )

        insert_data = table.insert.call_args.args[0]
        self.assertEqual(insert_data['data_limite_envio'], '2026-05-06T23:59:59-03:00')

    def test_upsert_pedido_master_updates_existing_by_pedido_bling_id(self):
        payload = {
            'id': 1,
            'numero': '123',
            'numeroLoja': '456',
            'total': 10,
            'data': '2026-05-02',
            'situacao': {'id': 2},
            'contato': {'nome': 'Cliente'},
            'itens': [],
        }

        table = MagicMock()
        table.update.return_value.eq.return_value.execute.return_value.data = [{'id': 321}]

        with patch.object(bos, '_find_existing_pedido_master_for_update', return_value={'id': 321}), \
             patch.object(bos.supabase_db, 'table', return_value=table), \
             patch.object(bos, '_resolve_situacao_interna', return_value=42), \
             patch.object(bos, '_upsert_itens_pedido'), \
             patch.object(bos.logger, 'info'):
            pedido_id = bos._upsert_pedido_master(
                payload,
                pedido_bling_id=11,
                pedido_shopee_id=None,
                bling_integration_id=22,
                marketplace_integration_id=None,
                canal_venda_id=None,
                is_flex=False,
                modalidade=None,
                shopee_data=None,
            )

        self.assertEqual(pedido_id, 321)
        table.update.return_value.eq.assert_called_once_with('id', 321)


if __name__ == '__main__':
    unittest.main()
