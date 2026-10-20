import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nistiprint_shared.database.supabase_db_service import supabase_db
with patch.object(supabase_db,'table',return_value=MagicMock()):
    from routes import gestao


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.secret_key='test'
        self.app.register_blueprint(gestao.gestao_bp)
        self.client=self.app.test_client()
        self.guard=patch.object(gestao,'require_request_permission',return_value=None)
        self.guard.start();self.addCleanup(self.guard.stop)
        self.user=patch.object(gestao,'get_current_user',return_value={'id':1})
        self.user.start();self.addCleanup(self.user.stop)

    def test_base_permission_blocks_report_before_data_access(self):
        with patch.object(gestao,'require_request_permission',return_value=('denied',403)),patch.object(gestao,'service') as service:
            r=self.client.get('/api/v2/gestao/resumo')
            self.assertEqual(r.status_code,403)
            service.assert_not_called()

    def test_detail_and_financial_permissions_are_separate(self):
        def guard(resource,action):
            return ('denied',403) if resource!='gestao' else None
        with patch.object(gestao,'require_request_permission',side_effect=guard):
            self.assertEqual(self.client.get('/api/v2/gestao/exportar').status_code,403)
            self.assertEqual(self.client.get('/api/v2/gestao/pedidos').status_code,403)
            self.assertEqual(self.client.put('/api/v2/gestao/financeiro/1',json={'components':{'net_payout':100}}).status_code,403)

    def test_no_finance_request_when_finance_permission_absent(self):
        fake=MagicMock()
        fake.report.return_value={}
        with patch.object(gestao,'user_has_permission',return_value=False),patch.object(gestao,'service',return_value=fake):
            r=self.client.get('/api/v2/gestao/resumo?start=2026-01-01&end=2026-01-02')
        self.assertEqual(r.status_code,200)
        self.assertFalse(fake.report.call_args.kwargs['include_finance'])

    def test_financial_order_details_redacted_without_detail_permission(self):
        fake=MagicMock();fake.report.return_value={'profitability':{'orders':[{'id':1}],'coverage':100}}
        with patch.object(gestao,'user_has_permission',side_effect=lambda u,r,a='ler':r=='gestao_financeiro'),patch.object(gestao,'service',return_value=fake):
            r=self.client.get('/api/v2/gestao/resumo')
        self.assertNotIn('orders',r.json['data']['profitability'])

    def test_invalid_dates_and_filter_ids(self):
        for query in ('start=bad','start=2026-01-02&end=2026-01-01','end=2099-01-01','account_id=-1','product_id=NaN','start=2000-01-01'):
            self.assertEqual(self.client.get('/api/v2/gestao/resumo?'+query).status_code,400,query)

    def test_database_failure_is_redacted(self):
        with patch.object(gestao,'user_has_permission',return_value=False),patch.object(gestao,'service',side_effect=RuntimeError('secret_token_and_email')):
            r=self.client.get('/api/v2/gestao/resumo')
        self.assertEqual(r.status_code,503)
        self.assertNotIn('secret_token',r.get_data(as_text=True))

    def test_csv_neutralizes_formulas(self):
        for value in ('=HYPERLINK("bad")','  +cmd','@SUM(1)','\tformula'):
            self.assertTrue(gestao.safe_cell(value).startswith("'"))

    def test_finance_missing_values_and_nonfinite_numbers_rejected(self):
        for data in ({'components':{}},{'components':{'taxes':'NaN'}},{'components':{'fees':-1}},{'components':{'net_payout':1},'settled':'false'}):
            self.assertEqual(self.client.put('/api/v2/gestao/financeiro/1',json=data).status_code,400)

    def test_collection_capability_is_allowlisted(self):
        with patch('routes.auth.admin_required',side_effect=lambda fn:fn):
            self.assertEqual(self.client.post('/api/v2/gestao/coletar/6',json={'capability':'https://evil.example'}).status_code,400)

    def test_goal_rejects_invalid_month_and_zero(self):
        for data in ({'month':'2026-10-02','metric':'sales','target':1},{'month':'2026-10-01','metric':'sales','target':0}):
            self.assertEqual(self.client.put('/api/v2/gestao/metas',json=data).status_code,400)

    def test_events_require_idempotency_uuid(self):
        self.assertEqual(self.client.post('/api/v2/gestao/apontamentos',json={'pedido_id':1,'stage':'producao'}).status_code,400)


if __name__=='__main__':
    unittest.main()
