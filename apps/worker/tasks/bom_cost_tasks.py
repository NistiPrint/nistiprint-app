"""Background propagation of product costs through BOM parent chains."""

from celery_config import celery_app
from datetime import datetime, timedelta, timezone
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.database.supabase_db_service import supabase_db


@celery_app.task(
    bind=True,
    name='tasks.bom_cost_tasks.propagate_composite_cost_to_parents',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def propagate_composite_cost_to_parents(self, product_id: str):
    product_service.propagate_composite_cost_to_parents(str(product_id))


@celery_app.task(
    bind=True,
    name='tasks.bom_cost_tasks.process_batch_recalculation',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def process_batch_recalculation(self, recalculation_id: str):
    """Recalculate costs for an atomically saved BOM batch; retry from its durable row."""
    query = supabase_db.table('bom_lote_recalculos').select('*').eq('id', recalculation_id).limit(1)
    records = supabase_db.execute_with_retry(query).data or []
    if not records:
        return {'status': 'missing'}
    job = records[0]
    if job.get('status') == 'concluido':
        return {'status': 'concluido'}
    supabase_db.table('bom_lote_recalculos').update({
        'status': 'processando', 'tentativas': int(job.get('tentativas') or 0) + 1,
        'ultimo_erro': None, 'updated_at': datetime.now(timezone.utc).isoformat(),
    }).eq('id', recalculation_id).execute()
    try:
        product_ids = sorted({int(value) for value in job.get('produto_ids') or []})
        for product_id in product_ids:
            product_service.update_composite_product_cost(str(product_id))
        for product_id in product_ids:
            product_service.propagate_composite_cost_to_parents(str(product_id))
        supabase_db.table('bom_lote_recalculos').update({
            'status': 'concluido', 'ultimo_erro': None, 'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', recalculation_id).execute()
        batch = supabase_db.table('bom_lotes').select('resultado').eq('id', job['lote_id']).limit(1).execute().data or []
        if batch:
            supabase_db.table('bom_lotes').update({
                'resultado': {**(batch[0].get('resultado') or {}), 'custos_status': 'concluido'},
            }).eq('id', job['lote_id']).execute()
        return {'status': 'concluido', 'produtos': len(product_ids)}
    except Exception as exc:
        supabase_db.table('bom_lote_recalculos').update({
            'status': 'falhou', 'ultimo_erro': str(exc)[:1000], 'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', recalculation_id).execute()
        batch = supabase_db.table('bom_lotes').select('resultado').eq('id', job['lote_id']).limit(1).execute().data or []
        if batch:
            supabase_db.table('bom_lotes').update({
                'resultado': {**(batch[0].get('resultado') or {}), 'custos_status': 'falhou', 'custos_erro': str(exc)[:300]},
            }).eq('id', job['lote_id']).execute()
        raise


@celery_app.task(name='tasks.bom_cost_tasks.dispatch_pending_batch_recalculations')
def dispatch_pending_batch_recalculations():
    """Recover durable cost jobs if the API stopped after committing its BOM batch."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    retryable = (supabase_db.table('bom_lote_recalculos').select('id,status,updated_at')
                 .in_('status', ['pendente', 'falhou']).lt('updated_at', cutoff)
                 .order('created_at').limit(25))
    stuck = (supabase_db.table('bom_lote_recalculos').select('id,status,updated_at')
             .eq('status', 'processando').lt('updated_at', stale_cutoff)
             .order('created_at').limit(25))
    jobs_by_id = {job['id']: job for job in (supabase_db.execute_with_retry(retryable).data or [])}
    jobs_by_id.update({job['id']: job for job in (supabase_db.execute_with_retry(stuck).data or [])})
    dispatched = 0
    for job in jobs_by_id.values():
        job_id = job['id']
        now = datetime.now(timezone.utc).isoformat()
        try:
            claim = supabase_db.table('bom_lote_recalculos').update({
                'status': 'processando', 'updated_at': now,
            }).eq('id', job_id).eq('status', job['status'])
            if job['status'] == 'processando':
                claim = claim.lt('updated_at', stale_cutoff)
            else:
                claim = claim.lt('updated_at', cutoff)
            if not (claim.execute().data or []):
                continue
            celery_app.send_task('tasks.bom_cost_tasks.process_batch_recalculation', args=[job_id])
            dispatched += 1
        except Exception as exc:
            supabase_db.table('bom_lote_recalculos').update({
                'status': 'falhou', 'ultimo_erro': str(exc)[:1000],
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).eq('id', job_id).execute()
    return {'dispatched': dispatched}
