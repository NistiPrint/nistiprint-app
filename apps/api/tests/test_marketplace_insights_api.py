import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nistiprint_shared.database.supabase_db_service import supabase_db
with patch.object(supabase_db,'table',return_value=MagicMock()):
    from routes import marketplace_insights as routes


class AccountInsightApiTests(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__);app.secret_key='test';app.register_blueprint(routes.marketplace_insights_bp)
        self.client=app.test_client()

    def test_anonymous_is_rejected_before_accessing_account(self):
        with patch('routes.auth._active_session_user',return_value=None),patch.object(routes,'MarketplaceInsightsService') as service:
            self.assertEqual(self.client.get('/api/v2/marketplace/installed/6/insights').status_code,401)
            service.assert_not_called()

    def test_management_read_permission_does_not_grant_integration_administration(self):
        with patch('routes.auth._active_session_user',return_value={'id':2,'is_admin':False}):
            self.assertEqual(self.client.post('/api/v2/marketplace/installed/6/insights',json={'action':'enable','capability':'ml_ads'}).status_code,403)

    def test_financial_configuration_requires_financial_permission(self):
        with patch('routes.auth._active_session_user',return_value={'id':1,'is_admin':True}),patch.object(routes,'require_request_permission',return_value=('denied',403)),patch.object(routes,'MarketplaceInsightsService') as service:
            self.assertEqual(self.client.post('/api/v2/marketplace/installed/6/insights',json={'action':'enable','capability':'ml_ads'}).status_code,403)
            service.return_value.configure.assert_not_called()

    def test_reads_only_requested_account(self):
        with patch('routes.auth._active_session_user',return_value={'id':1,'is_admin':True}),patch.object(routes,'MarketplaceInsightsService') as service:
            service.return_value.read.return_value={'account_id':7,'capabilities':[]}
            response=self.client.get('/api/v2/marketplace/installed/7/insights')
            self.assertEqual(response.status_code,200)
            service.return_value.read.assert_called_once_with(7)

    def test_provider_errors_are_redacted(self):
        with patch('routes.auth._active_session_user',return_value={'id':1,'is_admin':True}),patch.object(routes,'MarketplaceInsightsService') as service:
            service.return_value.read.side_effect=RuntimeError('private token')
            response=self.client.get('/api/v2/marketplace/installed/7/insights')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('private token',response.get_data(as_text=True))


if __name__=='__main__': unittest.main()
