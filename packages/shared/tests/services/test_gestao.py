import copy
import unittest
from datetime import date, datetime

from nistiprint_shared.services.gestao_projection import Catalog, TZ, number, project
from nistiprint_shared.services.gestao_service import analyze, contribution, paginate


def source(**changes):
    result={'generation':1,'order':{'id':1,'marketplace_integration_id':6,'marketplace_module_id':'shopee',
            'data_compra_marketplace':'2026-10-01T10:00:00-03:00','total_pedido':110,
            'marketplace_lifecycle_stage':'delivered','personalizado':True},
            'account_name':'Loja A','shopee':{'create_time':1790859600,'buyer_user_id':10,
                'recipient_address':{'state':'SP','city':'São Paulo'}},
            'items':[{'id':11,'sku_externo':'ABC','quantidade':2,'preco_unitario':50,'subtotal':100}],
            'names':[]}
    result.update(changes)
    return result


def catalog(costs=None):
    return Catalog([{'id':2,'sku':'ABC','nome':'Caderno','preco_custo':10}],[],costs or [])


def fact(day, id=1, account=6, buyer=10, stage='delivered'):
    s=source()
    s['order'].update(id=id,marketplace_integration_id=account,data_compra_marketplace=f'{day}T10:00:00-03:00',marketplace_lifecycle_stage=stage)
    s['shopee'].update(create_time=int(datetime.fromisoformat(f'{day}T10:00:00-03:00').timestamp()),buyer_user_id=buyer)
    return project(s,catalog())


class ProjectionTests(unittest.TestCase):
    def test_finite_numbers_and_explicit_zero(self):
        self.assertEqual(number(0),0)
        for v in (None,'',True,'NaN','Infinity','bad'):
            self.assertIsNone(number(v))

    def test_replay_and_scoped_buyer_identity(self):
        s=source()
        a=project(s,catalog())
        self.assertEqual(a,project(s,catalog()))
        b=copy.deepcopy(s)
        b['order']['marketplace_integration_id']=7
        self.assertNotEqual(a['buyer_key'],project(b,catalog())['buyer_key'])
        self.assertNotIn('10',a.keys())
        self.assertEqual(a['region'],'SP')

    def test_conflicting_product_alias_does_not_choose_arbitrarily(self):
        cat=Catalog([{'id':1,'sku':'ABC'},{'id':2,'sku':'ABC'}],[],[])
        p=project(source(),cat)
        self.assertEqual(p['items'][0]['mapping'],'conflict')
        self.assertIsNone(p['items'][0]['product_id'])

    def test_listing_variation_is_scoped_to_account(self):
        s=source(items=[{'id':11,'item_externo_id':'100','variacao_externa_id':'20'}])
        cat=Catalog([{'id':2}],[{'produto_id':2,'integration_id':7,'item_externo_id':'100','variacao_externa_id':'20'}],[])
        self.assertIsNone(project(s,cat)['items'][0]['product_id'])

    def test_current_cost_is_estimated_and_does_not_replace_history(self):
        costs=[{'produto_id':2,'valid_from':'2026-01-01T00:00:00-03:00','unit_cost':4,'source':'manual','estimated':False},
               {'produto_id':2,'valid_from':'2026-11-01T00:00:00-03:00','unit_cost':9,'source':'manual','estimated':False}]
        p=project(source(),catalog(costs))
        self.assertEqual(p['items'][0]['unit_cost'],4)
        self.assertFalse(p['items'][0]['cost_estimated'])
        self.assertTrue(project(source(),catalog())['items'][0]['cost_estimated'])

    def test_erp_date_has_no_fabricated_hour(self):
        s=source(shopee={})
        s['order']['marketplace_module_id']='amazonfba_classic'
        self.assertIsNone(project(s,catalog())['hour'])

    def test_status_unknown_not_silently_sold(self):
        s=source()
        s['order']['marketplace_lifecycle_stage']=None
        self.assertFalse(project(s,catalog())['eligible'])

    def test_full_refund_is_not_eligible_even_after_delivery(self):
        s=source()
        s['order']['marketplace_payment_status']='refunded'
        o=project(s,catalog())
        self.assertFalse(o['eligible'])
        self.assertEqual(o['stage'],'refunded')


class AnalyticsTests(unittest.TestCase):
    def report(self,rows,**kwargs):
        return analyze(rows,date(2026,10,1),date(2026,10,7),now=datetime(2026,10,20,tzinfo=TZ),**kwargs)

    def test_no_erp_or_pack_double_counting(self):
        rows=[fact('2026-10-01',id=1),fact('2026-10-01',id=2)]
        for o in rows:
            o['pack_id']='same-pack'
        report=self.report(rows)
        self.assertEqual(report['summary']['orders'],2)
        self.assertEqual(report['summary']['sales'],200)
        self.assertEqual(report['summary']['buyer_total'],220)

    def test_cancelled_and_returned_are_separate(self):
        report=self.report([fact('2026-10-01'),fact('2026-10-01',2,stage='cancelled'),fact('2026-10-01',3,stage='returned')])
        self.assertEqual(report['summary']['orders'],1)
        self.assertEqual(report['summary']['sales'],100)
        self.assertEqual(report['summary']['cancelled'],1)
        self.assertEqual(report['summary']['returned'],1)

    def test_weekday_average_includes_zero_sales_days(self):
        r=analyze([fact('2026-10-01')],date(2026,10,1),date(2026,10,14),now=datetime(2026,10,20,tzinfo=TZ))
        thursday=r['weekdays'][3]
        self.assertEqual(thursday['occurrences'],2)
        self.assertEqual(thursday['average_sales'],50)

    def test_recurrence_only_same_account_and_prior_history(self):
        report=self.report([fact('2026-09-20'),fact('2026-10-01',2),fact('2026-10-02',3,account=7)])
        self.assertEqual(report['customers']['identified'],2)
        self.assertEqual(report['customers']['returning'],1)
        self.assertNotIn('buyer_key',str(report))

    def test_names_preserve_compounds_and_only_success(self):
        o=fact('2026-10-01')
        o['names']=[{'id':'s1','item_id':11,'name':'Maria Clara','initial':None,'status':'SUCCESS','confirmed':False,'quantity':2},
                    {'id':'s2','item_id':11,'name':'maria clara','initial':None,'status':'SUCCESS','confirmed':True,'quantity':None},
                    {'id':'s3','item_id':11,'name':'Maria','initial':None,'status':'NEEDS_REVIEW','confirmed':False,'quantity':1}]
        r=self.report([o])
        self.assertEqual(len(r['names']),1)
        self.assertEqual(r['names'][0]['occurrences'],2)
        self.assertEqual(r['names'][0]['units'],2)
        self.assertEqual(r['names'][0]['confirmed'],1)

    def test_missing_tax_is_not_zero(self):
        o=fact('2026-10-01')
        o['finance']={'components':{'net_payout':80,'operating_cost':0},'settled':True}
        self.assertIsNone(contribution(o)['before_ads'])

    def test_unknown_sales_are_not_reported_as_zero(self):
        o=fact('2026-10-01')
        o['items'][0]['subtotal']=None
        r=self.report([o])
        self.assertIsNone(r['summary']['sales'])
        self.assertIsNone(r['products'][0]['sales'])
        self.assertEqual(r['summary']['sales_coverage'],0)

    def test_net_payout_does_not_subtract_fees_twice(self):
        o=fact('2026-10-01')
        o['finance']={'components':{'net_payout':80,'fees':20,'shipping':10,'taxes':0,'operating_cost':0,'ads':5},'settled':True}
        m=contribution(o)
        self.assertEqual(m['before_ads'],60)
        self.assertEqual(m['after_ads'],55)
        self.assertEqual(m['state'],'estimated')

    def test_returned_inventory_requires_explicit_cost(self):
        o=fact('2026-10-01',stage='returned')
        o['finance']={'components':{'net_payout':-5,'taxes':0,'operating_cost':0}}
        self.assertIsNone(contribution(o)['before_ads'])
        o['finance']['components']['cogs']=0
        self.assertEqual(contribution(o)['before_ads'],-5)

    def test_product_filter_does_not_allocate_order_payout(self):
        o=fact('2026-10-01')
        o['finance']={'components':{'net_payout':80,'taxes':0,'operating_cost':0}}
        r=self.report([o],filters={'product_id':2},include_finance=True)
        self.assertIsNone(r['profitability']['before_ads'])

    def test_financial_data_not_exposed_without_permission(self):
        o=fact('2026-10-01')
        o['finance']={'components':{'net_payout':9876,'taxes':0,'operating_cost':0}}
        r=self.report([o])
        self.assertNotIn('profitability',r)
        self.assertNotIn('9876',str(r))

    def test_forecast_backtest_and_insufficient_history(self):
        self.assertEqual(self.report([fact('2026-10-01')])['forecast']['status'],'insufficient_history')
        r=self.report([fact('2026-08-01'),fact('2026-10-01',2)])
        self.assertEqual(r['forecast']['test_days'],7)
        self.assertEqual(len(r['forecast']['days']),7)
        self.assertIsNotNone(r['forecast']['mae'])

    def test_incomplete_historical_coverage_disables_growth(self):
        self.assertIsNone(self.report([fact('2026-10-01')])['changes']['sales'])

    def test_pagination_does_not_stop_at_supabase_default_limit(self):
        class Query:
            def range(self,start,end):
                self.start,self.end=start,end
                return self
            def execute(self):
                return type('Result',(),{'data':list(range(2501))[self.start:self.end+1]})()
        self.assertEqual(len(list(paginate(Query))),2501)


if __name__=='__main__':
    unittest.main()
