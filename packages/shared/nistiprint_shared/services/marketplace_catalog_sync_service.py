"""Checkpointed, account-scoped listing synchronization."""
from importlib import import_module
from time import monotonic, sleep
from datetime import datetime, timezone

from nistiprint_shared.services.credential_resolver_service import credential_resolver_service


DRIVERS = {'mercadolivre': 'mercadolivre_catalog', 'shopee': 'shopee_catalog'}


class MarketplaceCatalogSyncService:
    def __init__(self, db):
        self.db = db

    def capabilities(self, integration):
        platform = (integration.get('platform_slug') or integration.get('module_id') or '').lower()
        module = DRIVERS.get(platform)
        if not module:
            return {'platform': platform, 'listings': False, 'statistics': False,
                    'status': 'unavailable', 'reason': 'catalog_adapter_unavailable'}
        driver = import_module(f'nistiprint_shared.services.platform_drivers.{module}')
        hydrated = credential_resolver_service.hydrate_integration(integration)
        hydrated['_catalog_reserve'] = self._budget_reserver(integration)
        result = driver.get_catalog_capabilities(hydrated)
        if not result.ok:
            return {'platform': platform, 'listings': False, 'statistics': False,
                    'status': 'unavailable', 'reason': result.error_type}
        return {'platform': platform, **result.value, 'status': 'available'}

    def sync_page(self, account_id):
        integrations = self.db.table('installed_integrations').select('*').eq('id', account_id).eq('is_active', True).limit(1).execute().data or []
        if not integrations:
            return {'status': 'account_missing'}
        integration = integrations[0]
        platform = (integration.get('platform_slug') or integration.get('module_id') or '').lower()
        module = DRIVERS.get(platform)
        if not module:
            return {'status': 'unavailable', 'reason': 'catalog_adapter_unavailable', 'platform': platform}
        claim = self.db.rpc('marketplace_catalog_sync_claim', {'p_account': account_id}).execute().data or {}
        if claim.get('status') == 'busy':
            return {'status': 'busy'}
        token, cursor = claim.get('owner_token'), claim.get('checkpoint') or {}
        driver = import_module(f'nistiprint_shared.services.platform_drivers.{module}')
        hydrated = credential_resolver_service.hydrate_integration(integration)
        hydrated['_catalog_reserve'] = self._budget_reserver(integration)
        try:
            page = driver.list_listings(hydrated, cursor)
            if not page.ok or page.partial:
                return self._fail(account_id, token, page)
            item_ids = (page.value or {}).get('item_ids') or []
            observed_at = datetime.now(timezone.utc).isoformat()
            details = driver.get_listing_details(hydrated, item_ids)
            if not details.ok or details.partial:
                return self._fail(account_id, token, details)
            value = page.value or {}
            saved = self.db.rpc('marketplace_catalog_sync_store_page', {
                'p_account': account_id, 'p_owner_token': token,
                'p_rows': [{**listing, 'observed_at': observed_at} for listing in (details.value or {}).get('listings') or []],
                'p_checkpoint': value.get('cursor') or {}, 'p_complete': bool(value.get('complete')),
            }).execute().data
            if not saved:
                return {'status': 'lease_lost'}
            return {'status': 'complete' if value.get('complete') else 'available',
                    'has_more': not bool(value.get('complete')), 'items': len(item_ids), 'item_ids': item_ids}
        except Exception:
            self.db.rpc('marketplace_catalog_sync_fail', {'p_account': account_id,
                'p_owner_token': token, 'p_error': 'catalog_sync_internal_error'}).execute()
            raise

    def refresh_item(self, integration, item_id, seller_id):
        """Fetch one seller-owned listing and persist it without touching scan state."""
        account_id = int(integration['id'])
        hydrated = credential_resolver_service.hydrate_integration(integration)
        hydrated['_catalog_reserve'] = self._budget_reserver(integration)
        driver = import_module('nistiprint_shared.services.platform_drivers.mercadolivre_catalog')
        started = datetime.now(timezone.utc).isoformat()
        response = driver.get_listing_details(hydrated, [item_id])
        if not response.ok or response.partial:
            return {'status':'error','error_type':response.error_type or 'partial_catalog_response',
                    'retryable':bool(response.retryable or response.partial),'retry_after':response.retry_after}
        listings = (response.value or {}).get('listings') or []
        if len(listings) != 1 or listings[0].get('item_externo_id') != item_id:
            return {'status':'error','error_type':'partial_catalog_response','retryable':True}
        if not seller_id or listings[0].get('seller_id') != str(seller_id):
            return {'status':'error','error_type':'marketplace_account_mismatch','retryable':False}
        result = self.db.rpc('marketplace_catalog_store_item', {
            'p_account':account_id,'p_row':listings[0],'p_observed_at':started,
        }).execute().data
        if result not in {'updated','stale'}:
            return {'status':'error','error_type':'catalog_store_unconfirmed','retryable':True}
        return {'status':'success','event_status':'catalog_updated' if result == 'updated' else 'catalog_stale',
                'marketplace_integration_id':account_id,'provider_resource_type':'catalog',
                'provider_resource_id':item_id,'provider_topic':'items'}

    def _budget_reserver(self, integration):
        account_id = int(integration['id'])
        scope = f"{(integration.get('platform_slug') or integration.get('module_id') or '').lower()}:app:{integration.get('app_profile_id') or 'default'}"

        def reserve():
            deadline = monotonic() + 60
            while monotonic() < deadline:
                allowed = self.db.rpc('marketplace_insights_budget', {
                    'p_account': account_id, 'p_interval': 10, 'p_scope': scope,
                }).execute().data
                if allowed:
                    return True
                sleep(1)
            return False
        return reserve

    def _fail(self, account_id, token, result):
        self.db.rpc('marketplace_catalog_sync_fail', {'p_account': account_id,
            'p_owner_token': token, 'p_error': (result.error_type or ('partial_catalog_response' if result.partial else 'provider_error'))[:100]}).execute()
        return {'status': 'failed', 'error_code': result.error_type,
                'retryable': bool(result.retryable), 'retry_after': result.retry_after}
