import unittest
from unittest.mock import patch

from nistiprint_shared.services.anuncio_reconciliacao_service import resolve_unit
from nistiprint_shared.services.marketplace_contracts import ProviderCallResult
from nistiprint_shared.services.platform_drivers import mercadolivre_catalog as ml, shopee_catalog as shopee
from nistiprint_shared.services.gestao_projection import Catalog,preserve_item_attribution


class ReconciliationTests(unittest.TestCase):
    def test_ordinary_refresh_preserves_even_unmapped_historical_attribution(self):
        projection={'sold_at':'2026-10-01T10:00:00-03:00','items':[
            {'sku':'ABC','product_id':20,'mapping':'matched','listing_title':'Título externo'}]}
        catalog=Catalog([{'id':20,'sku':'ABC','nome':'Produto novo'}],[],[])
        facts=[{'chave_grupo':'sku:abc','produto_id':None,'origem_atribuicao':'unmapped','anuncio_id':None,'unidade_anuncio_id':None}]
        preserved=preserve_item_attribution(projection,facts,catalog)
        self.assertIsNone(preserved['items'][0]['product_id'])
        self.assertEqual(preserved['items'][0]['mapping'],'unmapped')
    def test_manual_link_is_preserved_and_conflict_is_visible(self):
        unit = {'integration_id':6,'sku_externo':' abc ','produto_id':20,'origem_vinculo':'manual'}
        result = resolve_unit(unit,[{'id':10,'sku':'ABC','papel_catalogo':'individual'}],[])
        self.assertEqual(result,(20,'confirmed_conflict',[10]))

    def test_alias_of_another_account_cannot_resolve(self):
        result = resolve_unit({'integration_id':6,'sku_externo':'ABC'},[],[
            {'integration_id':7,'produto_id':20,'aprovado':True,'normalizado':'abc'}])
        self.assertEqual(result,(None,'unmapped',[]))

    def test_conflicting_alias_does_not_select_arbitrary_product(self):
        result = resolve_unit({'integration_id':6,'sku_externo':'ABC'},[{'id':10,'sku':'ABC'}],[
            {'integration_id':6,'produto_id':20,'aprovado':True,'normalizado':'abc'}])
        self.assertEqual(result,(None,'conflict',[10,20]))

    def test_unapproved_alias_requires_review(self):
        result = resolve_unit({'integration_id':6,'sku_externo':'ABC'},[{'id':10,'sku':'ABC'}],[
            {'integration_id':6,'produto_id':20,'aprovado':False,'normalizado':'abc'}])
        self.assertEqual(result,(None,'alias_pending',[10]))


class CatalogDriverTests(unittest.TestCase):
    def test_shopee_verified_empty_status_can_omit_item_list(self):
        response={'total_count':0,'has_next_page':False,'next':''}
        with patch.object(shopee,'_get',return_value=ProviderCallResult(True,response)):
            result=shopee.list_listings({}, {'status_index':2,'offset':0})
        self.assertTrue(result.ok)
        self.assertEqual(result.value['item_ids'],[])
        self.assertEqual(result.value['cursor'],{'status_index':3,'offset':0})

    def test_shopee_missing_nonempty_page_remains_an_error(self):
        response={'total_count':7,'has_next_page':False,'next':''}
        with patch.object(shopee,'_get',return_value=ProviderCallResult(True,response)):
            result=shopee.list_listings({}, {'status_index':3,'offset':5})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type,'invalid_catalog_response')

    def test_ml_empty_scan_is_terminal_even_with_scroll_id(self):
        with patch.object(ml,'_get',return_value=ProviderCallResult(True,{'results':[],'scroll_id':'same'})):
            result = ml.list_listings({}, {'seller_id':'seller','scroll_id':'same'})
        self.assertTrue(result.value['complete'])

    def test_shopee_model_attributes_and_decimal_price(self):
        response = {'model':[{'model_id':101,'model_sku':'BLUE','tier_index':[0],
                    'price_info':[{'current_price':12.35}]}],
                    'tier_variation':[{'name':'Cor','option_list':[{'option':'Azul'}]}]}
        with patch.object(shopee,'_get',return_value=ProviderCallResult(True,response)):
            result = shopee.get_listing_variations({},'10')
        unit = result.value['units'][0]
        self.assertEqual(unit['variacao_externa_id'],'101')
        self.assertEqual(unit['preco_observado'],'12.35')
        self.assertEqual(unit['atributos_variacao'],{'Cor':'Azul'})
        self.assertIsNone(unit['disponibilidade_observada'])

    def test_shopee_missing_details_is_not_a_complete_scan(self):
        with patch.object(shopee,'_get',return_value=ProviderCallResult(True,{'item_list':[]})):
            result = shopee.get_listing_details({},['10'])
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type,'partial_catalog_response')

    def test_shopee_cursor_cannot_repeat_without_progress(self):
        with patch.object(shopee,'_get',return_value=ProviderCallResult(True,{
            'item':[{'item_id':10}],'has_next_page':True,'next_offset':5})):
            result = shopee.list_listings({}, {'offset':5})
        self.assertEqual(result.error_type,'catalog_cursor_stalled')


if __name__ == '__main__':
    unittest.main()
