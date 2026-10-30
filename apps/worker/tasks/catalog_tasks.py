"""Scheduled catalog scans and account-scoped resumable synchronization."""
import os

from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db


@celery_app.task(bind=True, name='tasks.catalog_tasks.sync_account', soft_time_limit=180, time_limit=210, max_retries=6)
def sync_account(self, account_id, operation_id=None):
    from nistiprint_shared.services.marketplace_catalog_sync_service import MarketplaceCatalogSyncService
    service = MarketplaceCatalogSyncService(supabase_db)
    result = service.sync_page(int(account_id))
    if result.get('status') == 'complete':
        reconcile_account.apply_async(args=[account_id,0,operation_id],queue='marketplace_analytics')
        result['status'] = 'reconciling'
    if result.get('item_ids'):
        reconcile_page.apply_async(args=[account_id,result['item_ids']],queue='marketplace_analytics')
    from nistiprint_shared.services.catalog_operations import progress
    progress(operation_id, result)
    if result.get('status') == 'available' and result.get('has_more'):
        sync_account.apply_async(args=[account_id,operation_id], countdown=1, queue='marketplace_analytics')
    elif result.get('status') == 'failed' and result.get('retryable'):
        delay = max(1, int(result.get('retry_after') or 0), 30 * 2 ** min(self.request.retries, 6))
        raise self.retry(countdown=delay, max_retries=6)
    return result


@celery_app.task(name='tasks.catalog_tasks.sync_due', ignore_result=True)
def sync_due():
    if os.getenv('MARKETPLACE_CATALOG_ENABLED', '0').lower() in {'0', 'false', 'no'}:
        return {'status': 'disabled'}
    rows = supabase_db.table('installed_integrations').select('id,platform_slug,module_id').eq('is_active', True).execute().data or []
    suspended = {row['account_id'] for row in supabase_db.table('marketplace_catalog_sync').select('account_id').eq('status', 'unavailable').execute().data or []}
    for row in rows:
        if row['id'] not in suspended and (row.get('platform_slug') or row.get('module_id') or '').lower() in {'mercadolivre', 'shopee'}:
            sync_account.apply_async(args=[row['id']], queue='marketplace_analytics')


@celery_app.task(name='tasks.catalog_tasks.reconcile_account', soft_time_limit=120, time_limit=150)
def reconcile_account(account_id, after=0, operation_id=None):
    from nistiprint_shared.services.anuncio_reconciliacao_service import AnuncioReconciliacaoService
    from nistiprint_shared.services.catalog_operations import progress
    headers = supabase_db.table('marketplace_anuncios').select('id,item_externo_id').eq(
        'integration_id',int(account_id)).gt('id',int(after)).order('id').limit(25).execute().data or []
    result = AnuncioReconciliacaoService(supabase_db).reconcile(int(account_id), [h['item_externo_id'] for h in headers])
    result['status'] = 'available' if len(headers)==25 else 'organizing'
    progress(operation_id,result)
    if len(headers)==25:
        reconcile_account.apply_async(args=[account_id,headers[-1]['id'],operation_id],countdown=1,queue='marketplace_analytics')
    else:
        organize_account.apply_async(args=[account_id,0,operation_id],queue='marketplace_analytics')
    return result


@celery_app.task(bind=True, name='tasks.catalog_tasks.reconcile_page', soft_time_limit=120, time_limit=150, max_retries=6)
def reconcile_page(self, account_id, item_ids):
    from nistiprint_shared.services.anuncio_reconciliacao_service import AnuncioReconciliacaoService
    try:
        return AnuncioReconciliacaoService(supabase_db).reconcile(int(account_id),item_ids)
    except Exception as exc:
        raise self.retry(exc=RuntimeError(type(exc).__name__),countdown=30*2**min(self.request.retries,6))


@celery_app.task(bind=True, name='tasks.catalog_tasks.organize_account', max_retries=6)
def organize_account(self, account_id, after=0, operation_id=None, actor_id=None):
    from nistiprint_shared.services.catalog_operations import progress
    try:
        headers = supabase_db.table('marketplace_anuncios').select('id').eq('integration_id',int(account_id)).is_('absent_since','null').gt('id',int(after)).order('id').limit(25).execute().data or []
        counts = {}
        for header in headers:
            result = supabase_db.rpc('catalogo_organizar_anuncio', {'p_anuncio':header['id'],'p_actor':actor_id}).execute().data
            state = result['status']
            counts[state] = counts.get(state,0)+1
        result = {'status':'available' if len(headers)==25 else 'complete','processed':len(headers),'families':counts}
        progress(operation_id,result)
        if len(headers)==25:
            organize_account.apply_async(args=[account_id,headers[-1]['id'],operation_id,actor_id],queue='marketplace_analytics')
        return result
    except Exception as exc:
        raise self.retry(exc=RuntimeError(type(exc).__name__),countdown=30*2**min(self.request.retries,6))
