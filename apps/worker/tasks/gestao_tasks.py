"""Bounded analytics jobs. Never perform provider calls in the order ingest path."""
import logging
import os
from time import monotonic

from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.gestao_projection import Catalog, project
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
    listings=list(paginate(lambda:supabase_db.table('produto_anuncios').select('id,integration_id,item_externo_id,variacao_externa_id,produto_id,anuncio_id').order('id')))
    aliases=list(paginate(lambda:supabase_db.table('produtos_externos').select('produto_id,codigo_externo,plataforma,tipo,integration_id,aprovado,normalizado').order('id')))
    costs=list(paginate(lambda:supabase_db.table('gestao_custos').select('*').order('id')))
    catalog=Catalog(products,listings,costs,aliases)
    rows=[]
    for source in sources:
        try:
            rows.append(project(source,catalog))
        except (ValueError,TypeError,KeyError,AttributeError):
            logger.error('Projeção de gestão inválida pedido_id=%s',source.get('order',{}).get('id'))
    processed=supabase_db.rpc('gestao_finish',{'p_rows':rows}).execute().data if rows else 0
    logger.info('gestao_projection processed=%s claimed=%s duration_ms=%s',processed,len(sources),round((monotonic()-started)*1000))
    return {'processed':processed,'claimed':len(sources)}


@celery_app.task(bind=True, name='tasks.gestao_tasks.backfill_order_items',
                soft_time_limit=120, time_limit=150, max_retries=6)
def backfill_order_items(self, after=0, limit=100):
    """Populate granular facts from existing canonical projections in bounded batches."""
    result=supabase_db.rpc('gestao_backfill_order_item_facts',{
        'p_after':max(0,int(after)),'p_limit':max(1,min(int(limit),250)),
    }).execute().data or {}
    if result.get('has_more'):
        backfill_order_items.apply_async(args=[result.get('next_after',after),limit],
            countdown=1,queue='gestao_projection')
    return result


@celery_app.task(name='tasks.gestao_tasks.collect', soft_time_limit=120, time_limit=150, ignore_result=True)
def collect(account_id,capability):
    if os.getenv('MARKETPLACE_INSIGHTS_ENABLED','1').lower() in {'0','false','no'}:
        return {'status':'disabled'}
    from nistiprint_shared.services.gestao_collection_service import collect_batch
    result=collect_batch(supabase_db,int(account_id),capability)
    if result.get('status')=='available' and result.get('has_more'):
        collect.apply_async(kwargs={'account_id':account_id,'capability':capability},countdown=15,queue='marketplace_insights')
    return result


@celery_app.task(name='tasks.gestao_tasks.collect_due',ignore_result=True)
def collect_due():
    if os.getenv('MARKETPLACE_INSIGHTS_ENABLED','1').lower() in {'0','false','no'}:
        return {'status':'disabled'}
    from datetime import datetime,timedelta,timezone
    cutoff=datetime.now(timezone.utc).isoformat()
    rows=supabase_db.table('gestao_coletas').select('account_id,capability').eq('enabled',True).in_('status',['pending','available','failed']).lte('next_attempt_at',cutoff).order('next_attempt_at').limit(10).execute().data or []
    for row in rows:
        collect.apply_async(kwargs=row,queue='marketplace_insights')
