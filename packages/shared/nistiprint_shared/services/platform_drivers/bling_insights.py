"""Account-local marketplace intelligence. Never fetch order detail for projection."""
from datetime import datetime, timedelta
import re
from nistiprint_shared.services.gestao_projection import TZ, number
from nistiprint_shared.services.platform_drivers.insights_contract import CollectionError

def collect(db, account, capability, integration, cp, provider_get, metric, finance, order_batch):
    today = datetime.now(TZ).date()
    has_more = False
    from nistiprint_shared.services.bling.bling_client import BlingClient
    from nistiprint_shared.services.bling_order_processing_service import process_webhook
    client = BlingClient.create_client_for_integration_id(account)
    cp.setdefault('cycle_started_at', datetime.now(TZ).isoformat())
    page = int(cp.get('page', 1))
    params = {'pagina': page, 'limite': 5, 'dataInicial': (today - timedelta(days=365)).isoformat(), 'dataFinal': today.isoformat()}
    if cp.get('cycle_completed_at'):
        overlap = datetime.fromisoformat(cp['cycle_completed_at']) - timedelta(minutes=5)
        params['dataAlteracaoInicial'] = overlap.strftime('%Y-%m-%d %H:%M:%S')
    reserve=integration['_insights_reserve']
    if 'pending_order_ids' not in cp:
        reserve()
        data = client._request('GET', 'pedidos/vendas', params=params).get('data', [])
        cp['pending_order_ids']=[o['id'] for o in data]
        cp['page_count']=len(data)
    while cp['pending_order_ids']:
        reserve()
        detail = client._request('GET', f"pedidos/vendas/{int(cp['pending_order_ids'][0])}")['data']
        outcome = process_webhook(detail, bling_integration_hint=account)
        if outcome.get('success') is False:
            raise CollectionError('bling_ingest_incomplete')
        cp['pending_order_ids'].pop(0)
    cp.pop('pending_order_ids')
    has_more = cp.pop('page_count') == 5
    cp['page'] = page + 1 if has_more else 1
    if not has_more:
        cp['cycle_completed_at'] = cp.pop('cycle_started_at')
    return has_more

def extract(source):
    from .insights_contract import OrderInsights
    order=source['order']
    snapshot=source.get('snapshot') or {}
    raw=source.get('bling') or {}
    address=(raw.get('transporte') or {}).get('etiqueta') or {}
    facts={'sold_at':None,'buyer_id':(raw.get('contato') or {}).get('id'),
           'region':address.get('uf'),'city':address.get('municipio')}
    enrichments=()
    for key in ('region','city'):
        if isinstance(facts[key],dict):
            facts[key]=facts[key].get('name') or facts[key].get('id')
    # Version covers commercial changes; update timestamps alone do not invalidate analytics.
    facts['commercial']={k:order.get(k) for k in ('total_pedido','marketplace_lifecycle_stage','marketplace_payment_status','pack_id')}
    facts['items']=source.get('items') or []
    from nistiprint_shared.services.order_status_lexicon import SEED_LEXICON
    entry=SEED_LEXICON.get(('bling','order',str(order.get('marketplace_order_status') or order.get('status_original') or '').strip().upper()))
    facts['stage']=entry.stage if entry else 'unknown'
    return OrderInsights('bling',order.get('marketplace_integration_id'),
        str(order.get('marketplace_order_id') or order.get('codigo_pedido_externo') or raw.get('order_sn') or raw.get('id') or ''),
        facts,tuple(k for k in ('sold_at','buyer_id','region','city') if facts.get(k) in (None,'')),
        {'source':'persisted_order','order_detail_requests':0},enrichments)
