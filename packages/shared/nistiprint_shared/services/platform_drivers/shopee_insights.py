"""Account-local marketplace intelligence. Never fetch order detail for projection."""
from datetime import datetime, timedelta
import re
from nistiprint_shared.services.gestao_projection import TZ, number
from nistiprint_shared.services.platform_drivers.insights_contract import CollectionError
from nistiprint_shared.services.platform_drivers.insights_location import location

def collect(db, account, capability, integration, cp, provider_get, metric, finance, order_batch):
    today = datetime.now(TZ).date()
    has_more = False
    if capability in {'shopee_escrow'}:
        orders = order_batch(db, account, cp)
        for o in orders:
            external = str(o.get('marketplace_order_id') or o.get('codigo_pedido_externo') or '')
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}', external):
                raise CollectionError('invalid_order_identity')
            data = provider_get(integration, '/api/v2/payment/get_escrow_detail', {'order_sn': external})
            income = data.get('order_income') or {}
            if not income:
                raise CollectionError('financial_income_unavailable')
            components = {}
            for target, key in (('net_payout', 'escrow_amount_after_adjustment'), ('fees', 'commission_fee'), ('shipping', 'actual_shipping_fee'), ('seller_discount', 'voucher_from_seller')):
                value = number(income.get(key))
                if value is not None:
                    components[target] = value
            if 'net_payout' not in components and number(income.get('escrow_amount')) is not None:
                components['net_payout'] = number(income['escrow_amount'])
            db.rpc('marketplace_insights_store_finance', {'p_account': account, 'p_capability': capability, 'p_resource': external, 'p_version': o['insight_version'], 'p_components': components, 'p_settled': False, 'p_evidence': {'order_income': income}}).execute()
            cp['order_id'] = o['id']
        has_more = bool(orders)
        if not has_more:
            cp['order_id'] = 0
            cp['cycle_completed_at'] = datetime.now(TZ).isoformat()
    elif capability in {'shopee_product'}:
        listings = db.rpc('marketplace_insights_listing_batch',{'p_account':account,'p_after':int(cp.get('listing_id',0))}).execute().data or []
        for listing in listings:
            item = str(listing['item_externo_id'])
            if not re.fullmatch('[A-Za-z0-9_-]{1,64}', item):
                raise CollectionError('invalid_listing_identity')
            data = provider_get(integration, '/api/v2/product/get_item_extra_info', {'item_id_list': item})
            if not isinstance(data.get('item_list'), list):
                raise CollectionError('invalid_product_response')
            for d in data['item_list']:
                metric(db, account, item, today.isoformat(), 'counter', {k: d.get(k) for k in ('sale', 'views', 'likes', 'rating_star', 'comment_count')}, capability)
            cp['listing_id'] = listing['id']
        has_more = len(listings) == 5
        if not has_more:
            cp['listing_id'] = 0
    else:
        day = cp.get('day', (today - timedelta(days=90)).isoformat())
        next_day = (datetime.fromisoformat(day).date() + timedelta(days=1)).isoformat()
        data = provider_get(integration, '/api/v2/ads/get_all_cpc_ads_daily_performance', {'start_date': datetime.fromisoformat(day).strftime('%d-%m-%Y'), 'end_date': datetime.fromisoformat(next_day).strftime('%d-%m-%Y')})
        if not isinstance(data, list):
            raise CollectionError('invalid_ads_response')
        entries = data
        for d in entries:
            raw_day = str(d.get('date') or '')
            try:
                metric_day = datetime.strptime(raw_day, '%d-%m-%Y').date().isoformat()
            except ValueError:
                raise CollectionError('invalid_metric_date')
            metric(db, account, 'shop', metric_day, 'ads', d, capability)
        cp['day'] = next_day if next_day < today.isoformat() else (today - timedelta(days=14)).isoformat()
        has_more = next_day < today.isoformat()
    return has_more

def get(integration, resource, params=None, headers=None, request_json=None):
    import time
    import requests
    params = dict(params or {})
    platform = 'shopee'
    from nistiprint_shared.services.platform_drivers.shopee import _resolve_credentials, _generate_sign
    c = _resolve_credentials(integration)
    if not all((c.get(k) for k in ('partner_id', 'partner_key', 'shop_id', 'access_token'))):
        raise CollectionError('credentials_missing')
    stamp = int(time.time())
    params.update(partner_id=int(c['partner_id']), shop_id=int(c['shop_id']), access_token=c['access_token'], timestamp=stamp, sign=_generate_sign(int(c['partner_id']), c['partner_key'], resource, stamp, c['access_token'], int(c['shop_id'])))
    url = 'https://partner.shopeemobile.com' + resource
    headers = headers or {}
    response = request_json(requests.get, url, provider=platform, resource_type='analytics', params=params, headers=headers)
    if not response.ok:
        raise CollectionError(response.error_type or 'provider_error', response.status_code in {401, 403} or (response.status_code == 404 and resource.startswith('/advertising/')))
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
    raw = source.get('shopee') or {}
    raw = raw.get('raw') or raw
    address = raw.get('recipient_address') or {}
    facts = {'sold_at': raw.get('create_time'), 'buyer_id': raw.get('buyer_user_id'),
             'region': location(address.get('state')), 'city': location(address.get('city'))}
    enrichments = ('shopee_escrow',) if not (source.get('finance') or {}).get('settled') else ()
    facts['commercial'] = {k: order.get(k) for k in ('total_pedido', 'marketplace_lifecycle_stage', 'marketplace_payment_status', 'pack_id', 'data_pagamento_marketplace', 'data_compra_marketplace', 'data_venda', 'data_envio_marketplace', 'despachado_em', 'data_limite_envio', 'modalidade_logistica', 'servico_logistico', 'personalizado')}
    facts['items'] = [{k: v for k, v in i.items() if k not in {'updated_at', 'created_at'}} for i in source.get('items') or []]
    from nistiprint_shared.services.order_status_lexicon import SEED_LEXICON
    entry=SEED_LEXICON.get(('shopee','order',str(order.get('marketplace_order_status') or order.get('status_original') or '').strip().upper()))
    facts['stage']=entry.stage if entry else 'unknown'
    return OrderInsights('shopee', order.get('marketplace_integration_id'), str(order.get('marketplace_order_id') or order.get('codigo_pedido_externo') or raw.get('order_sn') or raw.get('id') or ''), facts, tuple((k for k in ('sold_at', 'buyer_id', 'region', 'city') if facts.get(k) in (None, ''))), {'source': 'persisted_order', 'order_detail_requests': 0}, enrichments if (order.get('marketplace_order_id') or order.get('codigo_pedido_externo') or raw.get('order_sn') or raw.get('id')) else ())
