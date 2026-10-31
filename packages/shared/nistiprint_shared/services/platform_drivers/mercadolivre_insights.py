"""Account-local marketplace intelligence. Never fetch order detail for projection."""
from datetime import datetime, timedelta
import re
import math
from nistiprint_shared.services.gestao_projection import TZ, number
from nistiprint_shared.services.platform_drivers.insights_contract import CollectionError
from nistiprint_shared.services.platform_drivers.insights_location import location


def observed_sale_fee(data, order_id):
    """Extract only the documented net sale fee for a complete, single order."""
    if not isinstance(data,dict) or data.get('errors') or not isinstance(data.get('results'),list):
        return {}
    rows=data['results']
    if type(data.get('total')) is not int or data['total'] != len(rows):
        return {}
    matched=[row for row in rows if isinstance(row,dict) and str(row.get('order_id') or '')==str(order_id)]
    if len(matched)!=1: return {}
    sale_fee=matched[0].get('sale_fee')
    if not isinstance(sale_fee,dict): return {}
    fee=sale_fee.get('net')
    if isinstance(fee,bool) or not isinstance(fee,(int,float)) or not math.isfinite(fee) or fee<0:
        return {}
    return {'sale_fee':fee}

def collect(db, account, capability, integration, cp, provider_get, metric, finance, order_batch):
    today = datetime.now(TZ).date()
    has_more = False
    if capability in {'ml_billing'}:
        orders = order_batch(db, account, cp)
        for o in orders:
            external = str(o.get('marketplace_order_id') or o.get('codigo_pedido_externo') or '')
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}', external):
                raise CollectionError('invalid_order_identity')
            data = provider_get(integration, '/billing/integration/group/ML/order/details', {'order_ids': external})
            db.rpc('marketplace_insights_store_finance', {'p_account': account, 'p_capability': capability, 'p_resource': external, 'p_version': o['insight_version'], 'p_components': observed_sale_fee(data,external), 'p_settled': False, 'p_evidence': data}).execute()
            cp['order_id'] = o['id']
        has_more = bool(orders)
        if not has_more:
            cp['order_id'] = 0
            cp['cycle_completed_at'] = datetime.now(TZ).isoformat()
    elif capability in {'ml_visits'}:
        listings = db.rpc('marketplace_insights_listing_batch',{'p_account':account,'p_after':int(cp.get('listing_id',0))}).execute().data or []
        for listing in listings:
            item = str(listing['item_externo_id'])
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}', item):
                raise CollectionError('invalid_listing_identity')
            data = provider_get(integration, f'/items/{item}/visits/time_window', {'last': int(cp.get('window_days', 7)), 'unit': 'day', 'ending': today.isoformat()})
            if not isinstance(data.get('results'), list):
                raise CollectionError('invalid_visits_response')
            for d in data['results']:
                metric(db, account, item, str(d['date'])[:10], 'visits', {'visits': d.get('total', d.get('total_visits'))}, capability,
                       timezone_name='UTC' if str(d['date']).endswith(('Z','+00:00')) else 'unspecified')
            cp['listing_id'] = listing['id']
        has_more = len(listings) == 5
        if not has_more:
            cp['listing_id'] = 0
    else:
        if not cp.get('advertiser'):
            advertisers = provider_get(integration, '/advertising/advertisers', {'product_id': 'PADS'}, {'Api-Version': '1'}).get('advertisers', [])
            selected = [a for a in advertisers if a.get('site_id') == 'MLB']
            configured = (integration.get('config') or {}).get('advertiser_id')
            if configured:
                selected = [a for a in selected if str(a['advertiser_id']) == str(configured)]
            if len(selected) != 1:
                raise CollectionError('advertiser_not_unique_or_unavailable', True)
            cp['advertiser'] = selected[0]
        advertiser = cp['advertiser']
        day = cp.get('day', (today - timedelta(days=90)).isoformat())
        offset = int(cp.get('offset', 0))
        data = provider_get(integration, f'/advertising/MLB/advertisers/{int(advertiser['advertiser_id'])}/product_ads/ad_groups/search', {'date_from': day, 'date_to': day, 'offset': offset, 'limit': 50, 'metrics': 'CLICKS,PRINTS,COST,DIRECT_AMOUNT,INDIRECT_AMOUNT,TOTAL_AMOUNT,ROAS,ACOS'}, {'api-version': '2'})
        if not isinstance(data.get('results'), list):
            raise CollectionError('invalid_ads_response')
        entries = data['results']
        for d in entries:
            metric(db, account, d['ad_group_id'], day, 'ads', d.get('metrics') or {}, capability)
        total = (data.get('paging') or {}).get('total', len(entries))
        cp['offset'] = offset + len(entries) if offset + len(entries) < total else 0
        if cp['offset'] == 0:
            next_day = (datetime.fromisoformat(day).date() + timedelta(days=1)).isoformat()
            cp['day'] = next_day if next_day < today.isoformat() else (today - timedelta(days=14)).isoformat()
            has_more = next_day < today.isoformat()
        else:
            has_more = True
    return has_more

def get(integration, resource, params=None, headers=None, request_json=None):
    import time
    import requests
    params = dict(params or {})
    platform = 'mercadolivre'
    from nistiprint_shared.services.platform_drivers.mercadolivre import _auth_headers
    url = 'https://api.mercadolibre.com' + resource
    headers = {**_auth_headers(integration), **(headers or {})}
    response = request_json(requests.get, url, provider=platform, resource_type='analytics', params=params, headers=headers)
    if not response.ok:
        raise CollectionError(response.error_type or 'provider_error', response.status_code in {401, 403} or (response.status_code == 404 and resource.startswith('/advertising/')), retry_after=response.retry_after)
    value = response.value or {}
    if value.get('error'):
        code = str(value['error'])
        code = code if re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',code) else 'provider_error'
        raise CollectionError(code, any((x in code for x in ('permission', 'auth', 'restricted', 'forbidden'))))
    return value.get('response', value)

def extract(source):
    from .insights_contract import OrderInsights
    order = source['order']
    snapshot = source.get('snapshot') or {}
    raw = source.get('ml') or {}
    shipment = source.get('shipment') or {}
    address = ((shipment.get('destination') or {}).get('shipping_address')
               or shipment.get('receiver_address') or {})
    facts = {'sold_at': raw.get('date_created'), 'buyer_id': (raw.get('buyer') or {}).get('id'),
             'region': location(address.get('state')), 'city': location(address.get('city'))}
    enrichments = ('ml_billing',) if not (source.get('finance') or {}).get('settled') else ()
    facts['commercial'] = {k: order.get(k) for k in ('total_pedido', 'marketplace_lifecycle_stage', 'marketplace_payment_status', 'pack_id', 'data_pagamento_marketplace', 'data_compra_marketplace', 'data_venda', 'data_envio_marketplace', 'despachado_em', 'data_limite_envio', 'modalidade_logistica', 'servico_logistico', 'personalizado')}
    facts['items'] = [{k: v for k, v in i.items() if k not in {'updated_at', 'created_at'}} for i in source.get('items') or []]
    from nistiprint_shared.services.order_status_lexicon import SEED_LEXICON
    entry=SEED_LEXICON.get(('mercadolivre','order',str(order.get('marketplace_order_status') or order.get('status_original') or '').strip().upper()))
    facts['stage']=entry.stage if entry else 'unknown'
    return OrderInsights('mercadolivre', order.get('marketplace_integration_id'), str(order.get('marketplace_order_id') or order.get('codigo_pedido_externo') or raw.get('order_sn') or raw.get('id') or ''), facts, tuple((k for k in ('sold_at', 'buyer_id', 'region', 'city') if facts.get(k) in (None, ''))), {'source': 'persisted_order', 'order_detail_requests': 0}, enrichments if (order.get('marketplace_order_id') or order.get('codigo_pedido_externo') or raw.get('order_sn') or raw.get('id')) else ())
