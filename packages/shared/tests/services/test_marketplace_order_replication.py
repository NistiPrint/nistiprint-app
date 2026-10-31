import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from nistiprint_shared.services.marketplace_order_replication import OrderReplication
from nistiprint_shared.services.platform_drivers import mercadolivre


class OrderReplicationTests(unittest.TestCase):
    def setUp(self):
        self.db=MagicMock()
        self.db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{'id':6,'platform_slug':'shopee','config':{'shop_id':42}}]
        self.claim={'owner_token':'token','window_start':'2026-10-27T00:00:00Z','window_end':'2026-10-30T00:00:00Z','cursor':{}}
        self.db.rpc.side_effect=lambda name,args: SimpleNamespace(execute=lambda:SimpleNamespace(data=self.claim if name=='marketplace_pedidos_claim' else True))
        budget=patch('nistiprint_shared.services.marketplace_order_replication.MarketplaceCatalogSyncService._budget_reserver',return_value=lambda:True)
        budget.start()
        self.addCleanup(budget.stop)

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.marketplace_webhook_ingest_service.process',return_value={'status':'success'})
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_next_cursor_is_saved_only_after_processing(self, page, process, hydrate):
        page.return_value={'orders':[{'external_id':'ORDER123'}],'more':True,'next_cursor':'next'}
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['status'],'available')
        self.assertEqual(process.call_args.args[1]['shop_id'],42)
        self.assertEqual(self.db.rpc.call_args_list[-1].args[1]['p_cursor']['cursor'],'next')

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_history_moves_to_next_daily_slice(self, page, hydrate):
        self.claim['window_start']='2026-07-01T00:00:00Z'
        page.return_value={'orders':[],'more':False,'next_cursor':None}
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['status'],'available')
        self.assertTrue(self.db.rpc.call_args_list[-1].args[1]['p_cursor']['slice_start'].startswith('2026-07-02'))

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_historical_discovery_uses_creation_date(self, page, hydrate):
        self.claim['search_field']='created'
        page.return_value={'orders':[],'more':False,'next_cursor':None}
        OrderReplication(self.db).run_page(6)
        self.assertEqual(page.call_args.args[1]['time_range_field'],'create_time')
        self.assertTrue(self.db.rpc.call_args_list[-1].args[1]['p_cursor']['slice_end'].startswith('2026-10-29'))

    @patch('nistiprint_shared.services.platform_drivers.mercadolivre._auth_headers',return_value={})
    @patch('nistiprint_shared.services.platform_drivers.mercadolivre.request_json')
    def test_mercadolivre_created_date_filter_uses_documented_parameter(self, request, headers):
        request.return_value=SimpleNamespace(ok=True,value={'results':[]})
        mercadolivre.get_orders_list({}, {'seller':'1','date_created_from':'2025-01-01T03:00:00Z','date_created_to':'2025-01-02T03:00:00Z'})
        params=request.call_args.kwargs['params']
        self.assertEqual(params['order.date_created.from'],'2025-01-01T03:00:00Z')
        self.assertEqual(params['order.date_created.to'],'2025-01-02T03:00:00Z')

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.marketplace_webhook_ingest_service.process',return_value={'status':'success'})
    @patch('nistiprint_shared.services.marketplace_order_replication.mercadolivre.get_orders_list')
    def test_mercadolivre_small_page_advances_one_offset(self, page, process, hydrate):
        account={'id':6,'platform_slug':'mercadolivre','config':{'seller_id':'42'}}
        self.db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data=[account]
        page.return_value=[{'external_id':'123'}]
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['status'],'available')
        self.assertEqual(page.call_args.args[1]['limit'],1)
        self.assertEqual(self.db.rpc.call_args_list[-1].args[1]['p_cursor']['offset'],1)

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.marketplace_webhook_ingest_service.process',return_value={'status':'error','error_type':'provider_failed'})
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_failure_never_advances_checkpoint(self, page, process, hydrate):
        page.return_value={'orders':[{'external_id':'ORDER123'}],'more':True,'next_cursor':'next'}
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.db.rpc.call_args_list[-1].args[1]['p_error'],'provider_failed')

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_repeated_cursor_fails_without_progress(self, page, hydrate):
        self.claim['cursor']={'cursor':'same'}
        page.return_value={'orders':[],'more':True,'next_cursor':'same'}
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['error_code'],'cursor_stalled')

    @patch('nistiprint_shared.services.marketplace_order_replication.credential_resolver_service.hydrate_integration',side_effect=lambda value:value)
    @patch('nistiprint_shared.services.marketplace_order_replication.shopee.get_orders_list_page')
    def test_provider_retry_after_is_preserved(self, page, hydrate):
        page.return_value={'orders':[{'error':'rate limit','error_type':'rate_limited','retry_after':900}],'more':False}
        result=OrderReplication(self.db).run_page(6)
        self.assertEqual(result['error_code'],'rate_limited')
        self.assertEqual(self.db.rpc.call_args_list[-1].args[1]['p_retry_after'],900)
