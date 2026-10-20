import unittest
from unittest.mock import MagicMock, patch
from nistiprint_shared.services.platform_drivers.insights_registry import extract, driver_for
from nistiprint_shared.services.gestao_projection import Catalog, project
from nistiprint_shared.services.marketplace_insights_service import MarketplaceInsightsService


class InsightTests(unittest.TestCase):
    def source(self,provider):
        return {'order':{'id':1,'marketplace_module_id':provider,'marketplace_integration_id':6,
            'marketplace_order_id':'123','data_venda':'2026-10-01','marketplace_lifecycle_stage':'delivered'},
            'generation':1,'shopee':{'create_time':1790863200,'buyer_user_id':90,'recipient_address':{'state':'SP','city':'São Paulo'}},
            'ml':{'date_created':'2026-10-01T10:00:00-03:00','buyer':{'id':90}},
            'shipment':{'receiver_address':{'state':{'name':'SP'},'city':{'name':'São Paulo'}}},'items':[]}

    def test_both_providers_reuse_persisted_details_without_http(self):
        for provider in ('shopee','mercadolivre'):
            with self.subTest(provider=provider),patch('requests.get',side_effect=AssertionError('Unexpected HTTP')):
                facts=project(self.source(provider),Catalog([],[],[]))
                self.assertEqual(facts['region'],'SP')
                self.assertEqual(facts['city'],'São Paulo')
                self.assertIsNotNone(facts['buyer_key'])
                self.assertEqual(facts['insights']['evidence']['order_detail_requests'],0)

    def test_version_ignores_bookkeeping_and_detects_commercial_changes(self):
        for provider in ('shopee','mercadolivre'):
            source=self.source(provider)
            before=extract(source).version
            source['order']['updated_at']='2026-10-20'
            self.assertEqual(before,extract(source).version)
            source['order']['marketplace_lifecycle_stage']='cancelled'
            self.assertNotEqual(before,extract(source).version)

    def test_identity_is_separated_by_provider_and_account(self):
        a=project(self.source('shopee'),Catalog([],[],[]))['buyer_key']
        b=project(self.source('mercadolivre'),Catalog([],[],[]))['buyer_key']
        source=self.source('shopee');source['order']['marketplace_integration_id']=7
        c=project(source,Catalog([],[],[]))['buyer_key']
        self.assertEqual(len({a,b,c}),3)

    def test_unknown_provider_never_resolves_an_erp_or_another_account(self):
        with self.assertRaises(ValueError): driver_for('amazon')

    def test_erp_contact_is_not_used_as_marketplace_buyer(self):
        for provider in ('shopee','mercadolivre'):
            source=self.source(provider)
            source['ml']['buyer']={}
            source['shopee']['buyer_user_id']=None
            source['snapshot']={'customer':{'raw':{'id':90}}}
            source['bling']={'contato':{'id':90}}
            self.assertIsNone(project(source,Catalog([],[],[]))['buyer_key'])

    def test_paid_ready_and_partial_refund_stages_remain_commercial_sales(self):
        for provider in ('shopee','mercadolivre'):
            for stage in ('fulfillment_ready','shipping_exception','partially_refunded'):
                source=self.source(provider);source['order']['marketplace_lifecycle_stage']=stage
                self.assertTrue(project(source,Catalog([],[],[]))['eligible'])
        from nistiprint_shared.services.gestao_service import summary
        source=self.source('mercadolivre');source['order']['marketplace_lifecycle_stage']='partially_refunded'
        self.assertEqual(summary([project(source,Catalog([],[],[]))])['partially_refunded'],1)

    def test_capability_cannot_run_against_other_provider(self):
        service=MarketplaceInsightsService(MagicMock())
        with patch.object(service,'account',return_value={'id':6,'module_id':'mercadolivre'}):
            with self.assertRaises(ValueError): service.configure(6,'shopee_ads','enable')

    def test_pause_keeps_checkpoint_and_running_lease(self):
        db=MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{'status':'available','checkpoint':{'day':'2026-10-01'}}]
        service=MarketplaceInsightsService(db)
        with patch.object(service,'account',return_value={'id':6,'module_id':'mercadolivre'}):
            service.configure(6,'ml_ads','pause')
        payload=db.table.return_value.upsert.call_args.args[0]
        self.assertFalse(payload['enabled'])
        self.assertNotIn('checkpoint',payload)
        self.assertNotIn('lease_until',payload)


if __name__=='__main__': unittest.main()
