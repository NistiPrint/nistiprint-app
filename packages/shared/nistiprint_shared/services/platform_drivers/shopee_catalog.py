"""Account-scoped Shopee product/model reads; no external writes."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
import time
import requests

from ..marketplace_contracts import ProviderCallResult
from ..marketplace_http import request_json
from .shopee import _resolve_credentials, _generate_sign

CATALOG_READ_PATHS = frozenset({
    '/api/v2/product/get_item_extra_info', '/api/v2/product/get_item_list',
    '/api/v2/product/get_model_list', '/api/v2/product/get_item_base_info',
})


def _get(integration, path, params):
    if path not in CATALOG_READ_PATHS:
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='catalog_read_path_forbidden')
    credentials = _resolve_credentials(integration)
    if not all(credentials.get(k) for k in ('partner_id', 'partner_key', 'shop_id', 'access_token')):
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='credential_action_required')
    reserve = integration.get('_catalog_reserve')
    if reserve and not reserve():
        return ProviderCallResult(False, provider='shopee', resource_type='catalog',
                                  error_type='analytics_budget_wait', retryable=True, retry_after=30)
    partner, shop, stamp = int(credentials['partner_id']), int(credentials['shop_id']), int(time.time())
    params = {**params, 'partner_id': partner, 'shop_id': shop, 'timestamp': stamp,
              'access_token': credentials['access_token'],
              'sign': _generate_sign(partner, credentials['partner_key'], path, stamp, credentials['access_token'], shop)}
    result = request_json(requests.get, 'https://partner.shopeemobile.com' + path,
                          provider='shopee', resource_type='catalog', params=params)
    if not result.ok:
        return result
    data = result.value or {}
    if data.get('error'):
        code = str(data['error']).lower()
        forbidden = any(part in code for part in ('permission', 'auth', 'forbidden', 'token', 'sign'))
        return ProviderCallResult(False, provider='shopee', resource_type='catalog',
            error_type='provider_access_forbidden' if forbidden else 'provider_parameter_error')
    if not isinstance(data.get('response'), dict):
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='invalid_catalog_response')
    return ProviderCallResult(True, value=data['response'], provider='shopee', resource_type='catalog')


def get_catalog_capabilities(integration):
    c = _resolve_credentials(integration)
    valid = all(c.get(k) for k in ('partner_id', 'partner_key', 'shop_id', 'access_token'))
    statistics = (integration.get('config') or {}).get('catalog_statistics_validated') is True
    return ProviderCallResult(valid, value={'listings': True, 'listing_details': True,
        'listing_statistics': statistics, 'statistics': ['counter'] if statistics else [], 'shop_id': str(c.get('shop_id') or '')} if valid else None,
        provider='shopee', resource_type='catalog', error_type=None if valid else 'credential_action_required')


def get_listing_statistics(integration, resources, period):
    if (integration.get('config') or {}).get('catalog_statistics_validated') is not True:
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='statistics_not_authenticated_validated')
    today = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    if period.get('date_from') != today or period.get('date_to') != today:
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='counter_history_unavailable')
    metrics = []
    for resource in dict.fromkeys(map(str,resources)):
        result = _get(integration,'/api/v2/product/get_item_extra_info',{'item_id_list':str(int(resource))})
        if not result.ok:
            return result
        entries = result.value.get('item_list')
        if not isinstance(entries,list) or len(entries)!=1 or str(entries[0].get('item_id'))!=resource:
            return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='invalid_counter_response')
        metrics.append({'resource_id':resource,'period_start':today,'period_end':today,'source':'shopee_product',
            'metric_type':'counter','semantic':'contador_acumulado','timezone':'America/Sao_Paulo',
            'metrics':{key:entries[0].get(key) for key in ('sale','views','likes')},'partial':result.partial})
    return ProviderCallResult(True,value={'metrics':metrics},provider='shopee',resource_type='catalog')


def list_listings(integration, cursor=None):
    cursor = cursor or {}
    statuses = ('NORMAL', 'UNLIST', 'BANNED', 'DELETED')
    index, offset = int(cursor.get('status_index', 0)), int(cursor.get('offset', 0))
    if index not in range(len(statuses)) or offset < 0:
        raise ValueError('Invalid Shopee catalog cursor')
    result = _get(integration, '/api/v2/product/get_item_list',
                  {'offset': offset, 'page_size': 5, 'item_status': statuses[index]})
    if not result.ok:
        return result
    data = result.value
    # Authenticated empty BANNED pages omit `item` entirely.
    if 'item' not in data and data.get('total_count') == 0 and data.get('has_next_page') is False:
        data = {**data, 'item': []}
    if not isinstance(data.get('item'), list) or not isinstance(data.get('has_next_page'), bool):
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='invalid_catalog_response')
    more = data['has_next_page']
    next_offset = data.get('next_offset')
    if more and (not data['item'] or next_offset is None or int(next_offset) <= offset):
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='catalog_cursor_stalled')
    complete = not more and index == len(statuses) - 1
    return ProviderCallResult(True, value={'item_ids': [str(i['item_id']) for i in data['item']],
        'cursor': {} if complete else {'status_index': index if more else index + 1,
                                     'offset': int(next_offset) if more else 0}, 'complete': complete},
        provider='shopee', resource_type='catalog')


def _unit(row, variation='', attributes=None):
    prices = row.get('price_info') or []
    price = prices[0].get('current_price') if prices else None
    stock = row.get('stock_info_v2') or {}
    quantity = (stock.get('summary_info') or {}).get('total_available_stock')
    return {'variacao_externa_id': variation, 'sku_externo': row.get('model_sku') or row.get('item_sku'),
            'atributos_variacao': attributes or {},
            'dados_observados': {key: row[key] for key in ('model_name', 'gtin_code', 'weight', 'dimension', 'price_info', 'stock_info_v2') if key in row},
            'preco_observado': str(Decimal(str(price))) if price is not None else None,
            'disponibilidade_observada': str(quantity) if quantity is not None else None}


def get_listing_variations(integration, item_id):
    result = _get(integration, '/api/v2/product/get_model_list', {'item_id': int(item_id)})
    if not result.ok:
        return result
    data = result.value
    if not isinstance(data.get('model'), list) or not data['model']:
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='invalid_model_response')
    tiers = data.get('tier_variation') or []
    units = []
    for row in data['model']:
        attrs = {}
        for tier, index in zip(tiers, row.get('tier_index') or []):
            options = tier.get('option_list') or []
            if 0 <= index < len(options):
                attrs[tier['name']] = options[index].get('option')
        units.append(_unit(row, str(row['model_id']), attrs))
    return ProviderCallResult(True, value={'units': units}, provider='shopee', resource_type='catalog')


def get_listing_details(integration, item_ids):
    if not item_ids:
        return ProviderCallResult(True, value={'listings': []}, provider='shopee', resource_type='catalog')
    result = _get(integration, '/api/v2/product/get_item_base_info', {'item_id_list': ','.join(str(int(i)) for i in item_ids)})
    if not result.ok:
        return result
    items = result.value.get('item_list')
    if not isinstance(items, list) or {str(i['item_id']) for i in items} != set(map(str, item_ids)):
        return ProviderCallResult(False, provider='shopee', resource_type='catalog', error_type='partial_catalog_response', retryable=True)
    listings = []
    for item in items:
        if item.get('has_model'):
            models = get_listing_variations(integration, item['item_id'])
            if not models.ok:
                return models
            units = models.value['units']
        else:
            units = [_unit(item)]
        images = (item.get('image') or {}).get('image_url_list') or []
        listings.append({'item_externo_id': str(item['item_id']), 'titulo': item.get('item_name'),
            'dados_observados': {key: item[key] for key in ('item_sku', 'description', 'category_id', 'brand', 'image', 'weight', 'dimension', 'logistic_info', 'gtin_code', 'attribute_list', 'condition', 'pre_order', 'price_info', 'stock_info_v2') if key in item},
            'imagem_comercial': images[0] if images else None, 'url': None,
            'situacao_original': item.get('item_status'),
            'situacao_normalizada': {'NORMAL': 'ativo', 'UNLIST': 'pausado', 'BANNED': 'em_revisao', 'DELETED': 'encerrado', 'SELLER_DELETE': 'encerrado', 'SHOPEE_DELETE': 'encerrado'}.get(item.get('item_status'), 'desconhecido'),
            'provider_updated_at': datetime.fromtimestamp(item['update_time'], timezone.utc).isoformat() if item.get('update_time') else None,
            'unidades': units})
    return ProviderCallResult(True, value={'listings': listings}, provider='shopee', resource_type='catalog')
