"""Scheduled catalog scans and account-scoped resumable synchronization."""
import os

from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db


@celery_app.task(bind=True, name='tasks.catalog_tasks.sync_account', soft_time_limit=180, time_limit=210, max_retries=6)
def sync_account(self, account_id):
    from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
    service = MarketplaceCatalogSyncService(supabase_db)
    result = service.sync_page(int(account_id))
    if result.get('status') == 'available' and result.get('has_more'):
        sync_account.apply_async(args=[account_id], countdown=1, queue='marketplace_analytics')
    elif result.get('status') == 'failed' and result.get('retryable'):
        delay = max(1, int(result.get('retry_after') or 30))
        raise self.retry(countdown=min(delay, 3600), max_retries=6)
    return result


@celery_app.task(name='tasks.catalog_tasks.sync_due', ignore_result=True)
def sync_due():
    if os.getenv('MARKETPLACE_CATALOG_ENABLED', '0').lower() in {'0', 'false', 'no'}:
        return {'status': 'disabled'}
    rows = supabase_db.table('installed_integrations').select('id,platform_slug,module_id').eq('is_active', True).execute().data or []
    for row in rows:
        if (row.get('platform_slug') or row.get('module_id') or '').lower() == 'mercadolivre':
            sync_account.apply_async(args=[row['id']], queue='marketplace_analytics')
