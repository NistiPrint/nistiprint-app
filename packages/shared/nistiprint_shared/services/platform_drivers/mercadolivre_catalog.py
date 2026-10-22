"""Read-only Mercado Livre listing catalog adapter."""
from __future__ import annotations

import requests

from nistiprint_shared.services.marketplace_contracts import ProviderCallResult
from nistiprint_shared.services.marketplace_http import request_json
from .mercadolivre import ML_API_HOST, _auth_headers


def _get(integration, path, params=None):
    reserve = integration.get('_catalog_reserve')
    if reserve and not reserve():
        return ProviderCallResult(False, provider='mercadolivre', resource_type='catalog',
            error_type='analytics_budget_wait', message='Limite compartilhado de consultas analíticas atingido.',
            retryable=True, retry_after=30)
    return request_json(requests.get, f'{ML_API_HOST}{path}', provider='Mercado Livre',
        resource_type='catalog', headers=_auth_headers(integration), params=params or {})


def get_catalog_capabilities(integration):
    config = integration.get('config') or {}
    credentials = integration.get('credentials') or {}
    account_ids = config.get('account_identifiers') or credentials.get('account_identifiers') or {}
    user_id = (config.get('user_id') or config.get('seller_id') or credentials.get('user_id')
               or credentials.get('seller_id') or account_ids.get('primary'))
    if not user_id:
        result = _get(integration, '/users/me')
        if not result.ok:
            return result
        user_id = (result.value or {}).get('id')
    if not user_id:
        return ProviderCallResult(False, provider='mercadolivre', resource_type='catalog',
            error_type='seller_identity_missing', message='Identificador do vendedor ausente.')
    return ProviderCallResult(True, value={'listings': True, 'listing_details': True,
        'listing_statistics': True, 'seller_id': str(user_id), 'statistics': ['visits']},
        provider='mercadolivre', resource_type='catalog')


def list_listings(integration, cursor=None):
    cursor = cursor or {}
    if cursor.get('seller_id'):
        seller_id = cursor['seller_id']
    else:
        capabilities = get_catalog_capabilities(integration)
        if not capabilities.ok:
            return capabilities
        seller_id = capabilities.value['seller_id']
    params = {'search_type': 'scan', 'limit': 10}
    if cursor.get('scroll_id'):
        params['scroll_id'] = cursor['scroll_id']
    result = _get(integration, f"/users/{seller_id}/items/search", params)
    if not result.ok:
        return result
    data = result.value or {}
    ids = data.get('results')
    if not isinstance(ids, list):
        return ProviderCallResult(False, provider='mercadolivre', resource_type='catalog',
            error_type='invalid_catalog_response', message='Resposta de catálogo inválida.')
    scroll = data.get('scroll_id')
    return ProviderCallResult(True, value={'item_ids': [str(value) for value in ids if value],
        'cursor': {'scroll_id': scroll, 'seller_id': str(seller_id)} if scroll else {}, 'complete': not bool(scroll)},
        provider='mercadolivre', resource_type='catalog')


def get_listing_details(integration, item_ids):
    listings = []
    for raw_id in item_ids:
        item_id = str(raw_id or '').strip()
        if not item_id or len(item_id) > 64 or not item_id.replace('-', '').isalnum():
            return ProviderCallResult(False, provider='mercadolivre', resource_type='catalog',
                error_type='invalid_listing_identity', message='Identificador de anúncio inválido.')
        result = _get(integration, f'/items/{item_id}', params={'include_attributes': 'all'})
        if not result.ok:
            return result
        item = result.value or {}
        variations = item.get('variations') or []
        item_sku = _seller_sku(item.get('attributes')) or item.get('seller_custom_field')
        units = []
        for variation in variations:
            seller_sku = _seller_sku(variation.get('attributes')) or variation.get('seller_custom_field') or item_sku
            variation_attributes = {
                str(attribute.get('name') or attribute.get('id') or 'Atributo'): attribute.get('value_name')
                for attribute in variation.get('attribute_combinations') or []
                if attribute.get('value_name') not in (None, '')
            }
            units.append({'variacao_externa_id': str(variation.get('id') or ''),
                'sku_externo': seller_sku,
                'atributos_variacao': variation_attributes,
                'preco_observado': variation.get('price', item.get('price')),
                'disponibilidade_observada': str(variation.get('available_quantity', item.get('available_quantity', ''))),
            })
        if not units:
            units.append({'variacao_externa_id': '', 'sku_externo': item_sku,
                'atributos_variacao': {},
                'preco_observado': item.get('price'),
                'disponibilidade_observada': str(item.get('available_quantity', ''))})
        updated = item.get('last_updated') or item.get('date_created')
        listings.append({'item_externo_id': item_id, 'titulo': item.get('title'),
            'imagem_comercial': item.get('secure_thumbnail') or item.get('thumbnail'), 'url': item.get('permalink'),
            'situacao_original': item.get('status'), 'situacao_normalizada': normalize_status(item.get('status')),
            'user_product_id': item.get('user_product_id'), 'familia_externa_id': item.get('family_name'),
            'catalogo_externo_id': item.get('catalog_product_id'), 'provider_updated_at': updated,
            'unidades': units})
    return ProviderCallResult(True, value={'listings': listings}, provider='mercadolivre', resource_type='catalog')


def normalize_status(value):
    status = str(value or '').strip().lower()
    return {'active': 'ativo', 'paused': 'pausado', 'closed': 'encerrado',
            'under_review': 'em_revisao', 'inactive': 'encerrado'}.get(status, 'desconhecido')


def _seller_sku(attributes):
    for attribute in attributes or []:
        key = str(attribute.get('id') or attribute.get('name') or '').strip().upper().replace('-', '_')
        if key == 'SELLER_SKU' and attribute.get('value_name') not in (None, ''):
            return str(attribute['value_name'])
    return None
