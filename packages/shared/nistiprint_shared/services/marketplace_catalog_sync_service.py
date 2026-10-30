"""Checkpointed, account-scoped listing synchronization."""
from importlib import import_module
from time import monotonic, sleep

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
            details = driver.get_listing_details(hydrated, item_ids)
            if not details.ok or details.partial:
                return self._fail(account_id, token, details)
            value = page.value or {}
            saved = self.db.rpc('marketplace_catalog_sync_store_page', {
                'p_account': account_id, 'p_owner_token': token,
                'p_rows': (details.value or {}).get('listings') or [],
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
