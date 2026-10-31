"""Bounded analytics jobs. Never perform provider calls in the order ingest path."""
import logging
import os
from time import monotonic

from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db


@celery_app.task(name='tasks.gestao_tasks.replicate_orders', soft_time_limit=240, time_limit=270)
def replicate_orders(account_id):
    from nistiprint_shared.services.marketplace_order_replication import OrderReplication
    from nistiprint_shared.services.catalog_operations import progress
    result=OrderReplication(supabase_db).run_page(int(account_id))
    if result.get('operation_id'):
        progress(result['operation_id'],result)
    if result.get('status') == 'available':
        replicate_orders.apply_async(args=[account_id],countdown=1,queue='marketplace_insights')
    return result


@celery_app.task(name='tasks.gestao_tasks.replicate_orders_due', ignore_result=True)
def replicate_orders_due():
    if os.getenv('MARKETPLACE_ORDER_REPLICATION_ENABLED','0').lower() in {'0','false','no'}:
        from datetime import datetime, timezone
        now=datetime.now(timezone.utc).isoformat()
        rows=supabase_db.table('marketplace_pedidos_coleta').select('account_id').in_('status',['available','failed','running']).lte('next_attempt_at',now).lte('lease_until',now).execute().data or []
        for row in rows:
            replicate_orders.apply_async(args=[row['account_id']],queue='marketplace_insights')
        return {'status':'recovering','scheduled':len(rows)}
    accounts=supabase_db.table('installed_integrations').select('id,platform_slug,module_id').eq('is_active',True).execute().data or []
    for row in accounts:
        if (row.get('platform_slug') or row.get('module_id') or '').lower() in {'shopee','mercadolivre'}:
            replicate_orders.apply_async(args=[row['id']],queue='marketplace_insights')
    return {'status':'scheduled'}
from nistiprint_shared.services.gestao_projection import Catalog, project, preserve_item_attribution
from nistiprint_shared.services.gestao_service import paginate

logger = logging.getLogger(__name__)


@celery_app.task(name='tasks.gestao_tasks.refresh', soft_time_limit=120, time_limit=150, ignore_result=True)
def refresh(limit=100):
    started=monotonic()
    supabase_db.rpc('gestao_expand_scopes',{}).execute()
    supabase_db.rpc('gestao_refresh_daily',{}).execute()
    sources=supabase_db.rpc('gestao_claim',{'p_limit':max(1,min(int(limit),250))}).execute().data
    if not sources:
        return {'processed':0}
    products=list(paginate(lambda:supabase_db.table('produtos').select('id,nome,sku,parent_id,categoria_id,formato,papel_catalogo,estrutura,preco_custo').order('id')))
    listings=list(paginate(lambda:supabase_db.table('produto_anuncios').select('id,integration_id,item_externo_id,variacao_externa_id,produto_id,anuncio_id,origem_vinculo').order('id')))
    aliases=list(paginate(lambda:supabase_db.table('produtos_externos').select('produto_id,codigo_externo,plataforma,tipo,integration_id,aprovado,normalizado').order('id')))
    costs=list(paginate(lambda:supabase_db.table('gestao_custos').select('*').order('id')))
    catalog=Catalog(products,listings,costs,aliases)
    source_ids=[source.get('order',{}).get('id') for source in sources]
    item_facts=list(paginate(lambda:supabase_db.table('gestao_fatos_item').select('*').in_('pedido_id',source_ids).order('id')))
    by_order={}
    for fact in item_facts:
        by_order.setdefault(fact['pedido_id'],[]).append(fact)
    rows=[]
    for source in sources:
        try:
            projection=project(source,catalog)
            rows.append(preserve_item_attribution(projection,by_order.get(source['order']['id'],[]),catalog))
        except (ValueError,TypeError,KeyError,AttributeError):
            logger.error('Projeção de gestão inválida pedido_id=%s',source.get('order',{}).get('id'))
    processed=supabase_db.rpc('gestao_finish',{'p_rows':rows}).execute().data if rows else 0
    logger.info('gestao_projection processed=%s claimed=%s duration_ms=%s',processed,len(sources),round((monotonic()-started)*1000))
    return {'processed':processed,'claimed':len(sources)}


@celery_app.task(bind=True, name='tasks.gestao_tasks.backfill_order_items',
                soft_time_limit=120, time_limit=150, max_retries=6)
def backfill_order_items(self, after=0, limit=100, operation_id=None):
    """Populate granular facts from existing canonical projections in bounded batches."""
    result=supabase_db.rpc('gestao_backfill_order_item_facts',{
        'p_after':max(0,int(after)),'p_limit':max(1,min(int(limit),250)),
    }).execute().data or {}
    from nistiprint_shared.services.catalog_operations import progress
    progress(operation_id,result)
    if result.get('has_more'):
        backfill_order_items.apply_async(args=[result.get('next_after',after),limit,operation_id],
            countdown=1,queue='gestao_projection')
    return result


@celery_app.task(name='tasks.gestao_tasks.collect', soft_time_limit=120, time_limit=150, ignore_result=True)
def collect(account_id,capability):
    if capability in {'ml_visits','shopee_product'} and os.getenv('MARKETPLACE_STATISTICS_ENABLED','0').lower() in {'0','false','no'}:
        return {'status':'disabled'}
    if os.getenv('MARKETPLACE_INSIGHTS_ENABLED','1').lower() in {'0','false','no'}:
        return {'status':'disabled'}
    from nistiprint_shared.services.gestao_collection_service import collect_batch
    result=collect_batch(supabase_db,int(account_id),capability)
    if result.get('status')=='available' and result.get('has_more'):
        collect.apply_async(kwargs={'account_id':account_id,'capability':capability},countdown=15,queue='marketplace_analytics' if capability in {'ml_visits','shopee_product'} else 'marketplace_insights')
    return result


@celery_app.task(name='tasks.gestao_tasks.collect_due',ignore_result=True)
def collect_due():
    if os.getenv('MARKETPLACE_INSIGHTS_ENABLED','1').lower() in {'0','false','no'}:
        return {'status':'disabled'}
    from datetime import datetime,timedelta,timezone
    cutoff=datetime.now(timezone.utc).isoformat()
    query=supabase_db.table('gestao_coletas').select('account_id,capability').eq('enabled',True).in_('status',['pending','available','failed']).lte('next_attempt_at',cutoff)
    if os.getenv('MARKETPLACE_STATISTICS_ENABLED','0').lower() in {'0','false','no'}:
        query=query.not_.in_('capability',['ml_visits','shopee_product'])
    rows=query.order('next_attempt_at').limit(10).execute().data or []
    for row in rows:
        collect.apply_async(kwargs=row,queue='marketplace_analytics' if row['capability'] in {'ml_visits','shopee_product'} else 'marketplace_insights')


@celery_app.task(name='tasks.gestao_tasks.statistics_due', ignore_result=True)
def statistics_due():
    """Wake enabled traffic collectors at 03:00; continuations remain bounded."""
    if os.getenv('MARKETPLACE_STATISTICS_ENABLED', '0').lower() in {'0', 'false', 'no'}:
        return {'status': 'disabled'}
    from datetime import datetime
    from nistiprint_shared.services.gestao_projection import TZ
    rows = supabase_db.table('gestao_coletas').select('account_id,capability').eq('enabled', True).in_(
        'capability', ['ml_visits', 'shopee_product']).in_('status', ['pending','available','failed']).lte(
        'next_attempt_at', datetime.now(TZ).isoformat()).execute().data or []
    for row in rows:
        collect.apply_async(kwargs=row, queue='marketplace_analytics')
    return {'scheduled': len(rows)}


@celery_app.task(bind=True, name='tasks.gestao_tasks.reprocess_items', soft_time_limit=120, time_limit=150, max_retries=6)
def reprocess_items(self, request_id):
    result = supabase_db.rpc('gestao_item_reprocessamento_batch', {'p_token':request_id,'p_limit':25}).execute().data or {}
    if result.get('has_more'):
        reprocess_items.apply_async(args=[request_id], countdown=1, queue='gestao_projection')
    return result


@celery_app.task(name='tasks.gestao_tasks.reprocess_pending', ignore_result=True)
def reprocess_pending():
    """Recover confirmed requests after broker/process interruption."""
    rows=supabase_db.table('gestao_item_reprocessamentos').select('id').in_(
        'status',['queued','running']).order('created_at').limit(10).execute().data or []
    for row in rows:
        reprocess_items.apply_async(args=[row['id']],queue='gestao_projection')
    return {'scheduled':len(rows)}
