import unittest
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nistiprint_shared.services import gestao_collection_service as collections
from nistiprint_shared.services.marketplace_contracts import ProviderCallResult


class CollectionTests(unittest.TestCase):
    def db_for(self,platform,checkpoint=None):
        db=MagicMock()
        db.rpc.return_value.execute.return_value.data=True
        tables={name:MagicMock() for name in ('gestao_coletas','installed_integrations','gestao_metricas_anuncio','gestao_metricas_anuncio_periodo')}
        for table in tables.values():
            for method in ('select','eq','limit','single','update','upsert'):
                getattr(table,method).return_value=table
        tables['gestao_coletas'].execute.return_value.data={'checkpoint':checkpoint or {}}
        tables['installed_integrations'].execute.return_value.data=[{'id':6,'module_id':platform,'platform_slug':platform}]
        db.table.side_effect=lambda name:tables[name]
        resolver=SimpleNamespace(credential_resolver_service=SimpleNamespace(hydrate_integration=lambda row:row))
        return db,tables,resolver

    def test_shopee_ads_dates_and_response_are_normalized(self):
        db,tables,resolver=self.db_for('shopee',{'day':'2026-10-01'})
        with patch.dict(sys.modules,{'nistiprint_shared.services.credential_resolver_service':resolver}), \
             patch.object(collections,'provider_get',return_value=[{'date':'01-10-2026','expense':10}]) as provider:
            result=collections.collect_batch(db,6,'shopee_ads')
        self.assertEqual(result['status'],'available')
        self.assertEqual(provider.call_args.args[2],{'start_date':'01-10-2026','end_date':'02-10-2026'})
        self.assertEqual(tables['gestao_metricas_anuncio'].upsert.call_args.args[0]['day'],'2026-10-01')
        period=tables['gestao_metricas_anuncio_periodo'].upsert.call_args.args[0]
        self.assertEqual((period['periodo_inicio'],period['periodo_fim'],period['semantica']),('2026-10-01','2026-10-01','diaria'))

    def test_unexpected_ads_shape_does_not_advance_checkpoint(self):
        db,tables,resolver=self.db_for('shopee',{'day':'2026-10-01'})
        with patch.dict(sys.modules,{'nistiprint_shared.services.credential_resolver_service':resolver}), \
             patch.object(collections,'provider_get',return_value={'unknown':[]}):
            result=collections.collect_batch(db,6,'shopee_ads')
        self.assertEqual(result['status'],'failed')
        saved=tables['gestao_coletas'].update.call_args.args[0]
        self.assertEqual(saved['checkpoint']['day'],'2026-10-01')
        self.assertEqual(saved['error_code'],'invalid_ads_response')

    def test_denial_pauses_collection_without_leaking_message(self):
        db,tables,resolver=self.db_for('shopee',{'day':'2026-10-01'})
        with patch.dict(sys.modules,{'nistiprint_shared.services.credential_resolver_service':resolver}), \
             patch.object(collections,'provider_get',side_effect=collections.CollectionError('permission_denied',True)):
            result=collections.collect_batch(db,6,'shopee_ads')
        self.assertEqual(result['status'],'forbidden')
        self.assertFalse(result['has_more'])
        self.assertEqual(tables['gestao_coletas'].update.call_args.args[0]['lease_until'],'-infinity')

    def test_provider_http_denial_is_actionable(self):
        with patch.object(collections,'request_json',return_value=ProviderCallResult(False,status_code=403,error_type='provider_access_forbidden')), \
             patch('nistiprint_shared.services.platform_drivers.mercadolivre._auth_headers',return_value={'Authorization':'Bearer secret'}):
            with self.assertRaises(collections.CollectionError) as error:
                collections.provider_get({'id':1,'module_id':'mercadolivre'},'/items/MLB1/visits/time_window')
        self.assertTrue(error.exception.forbidden)
        self.assertNotIn('secret',error.exception.code)

    def test_shopee_application_denial_with_http_200(self):
        credentials={'partner_id':1,'shop_id':2,'access_token':'token','partner_key':'key'}
        with patch.object(collections,'request_json',return_value=ProviderCallResult(True,{'error':'error_api_permission','message':'private info'})), \
             patch('nistiprint_shared.services.platform_drivers.shopee._resolve_credentials',return_value=credentials):
            with self.assertRaises(collections.CollectionError) as error:
                collections.provider_get({'module_id':'shopee'},'/api/v2/payment/get_escrow_detail')
        self.assertTrue(error.exception.forbidden)
        self.assertEqual(error.exception.code,'error_api_permission')

    def test_manual_reconciliation_not_overwritten_by_provider(self):
        db=MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[{'source':'manual','components':{'taxes':10}}]
        collections.finance(db,1,{'net_payout':20},'shopee_escrow',False,{})
        db.table.return_value.upsert.assert_not_called()

    def test_missing_financial_components_stay_missing(self):
        db=MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[]
        collections.finance(db,1,{'net_payout':20},'shopee_escrow',False,{})
        payload=db.table.return_value.upsert.call_args.args[0]
        self.assertNotIn('taxes',payload['components'])
        self.assertFalse(payload['settled'])

    def test_exclusive_collection_lease_skips_duplicate(self):
        db=MagicMock()
        db.rpc.return_value.execute.return_value.data=False
        self.assertEqual(collections.collect_batch(db,6,'ml_visits'),{'status':'busy'})
        db.table.assert_not_called()

    def test_unknown_capability_cannot_call_arbitrary_resource(self):
        db=MagicMock()
        with self.assertRaises(ValueError):
            collections.collect_batch(db,6,'https://external.example')
        db.rpc.assert_not_called()


if __name__=='__main__':
    unittest.main()
