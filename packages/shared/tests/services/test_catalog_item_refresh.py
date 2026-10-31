import unittest
from unittest.mock import MagicMock, patch
from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
from nistiprint_shared.services.marketplace_contracts import ProviderCallResult


class TargetedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.rpc.return_value.execute.return_value.data = 'updated'
        self.integration = {'id':6, 'platform_slug':'mercadolivre'}

    def refresh(self, listing, seller='42'):
        module = MagicMock()
        module.get_listing_details.return_value = ProviderCallResult(True, {'listings':[listing]})
        with patch('nistiprint_shared.services.marketplace_catalog_sync_service.import_module',return_value=module), \
             patch('nistiprint_shared.services.marketplace_catalog_sync_service.credential_resolver_service.hydrate_integration',return_value={}):
            return MarketplaceCatalogSyncService(self.db).refresh_item(self.integration,'MLB123',seller)

    def test_foreign_seller_cannot_write(self):
        result = self.refresh({'item_externo_id':'MLB123','seller_id':'99'})
        self.assertEqual(result['error_type'],'marketplace_account_mismatch')
        self.db.rpc.assert_not_called()

    def test_matching_seller_uses_targeted_rpc(self):
        result = self.refresh({'item_externo_id':'MLB123','seller_id':'42','unidades':[]})
        self.assertEqual(result['event_status'],'catalog_updated')
        self.assertEqual(self.db.rpc.call_args.args[0],'marketplace_catalog_store_item')
        self.assertEqual(self.db.rpc.call_args.args[1]['p_account'],6)

    def test_mismatched_listing_cannot_write(self):
        result = self.refresh({'item_externo_id':'MLB456','seller_id':'42'})
        self.assertEqual(result['error_type'],'partial_catalog_response')
        self.db.rpc.assert_not_called()

    def test_unconfirmed_storage_is_retryable(self):
        self.db.rpc.return_value.execute.return_value.data = None
        result = self.refresh({'item_externo_id':'MLB123','seller_id':'42','unidades':[]})
        self.assertEqual(result['status'],'error')
        self.assertTrue(result['retryable'])
