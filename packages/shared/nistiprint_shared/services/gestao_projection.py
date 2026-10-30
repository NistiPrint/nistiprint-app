"""Pure, replayable projection of canonical orders. No provider or database writes."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Sao_Paulo')


def number(value):
    if value is None or isinstance(value, bool) or value == '':
        return None
    try:
        result = Decimal(str(value))
        return float(result) if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def local_time(value):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, TZ)
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def path(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class Catalog:
    def __init__(self, products, listings, costs, aliases=None):
        self.products = {p['id']: p for p in products}
        self.skus = defaultdict(set)
        self.listings = defaultdict(set)
        self.listing_units = {}
        self.costs = defaultdict(list)
        self.aliases = defaultdict(set)
        for p in products:
            if p.get('sku') and not self._is_model(p):
                self.skus[p['sku'].strip().casefold()].add(p['id'])
        for a in listings:
            self.listing_units[(a['integration_id'], str(a['item_externo_id']),
                                str(a.get('variacao_externa_id') or ''))] = a
            if a.get('produto_id') in self.products:
                self.listings[(a['integration_id'], str(a['item_externo_id']),
                               str(a.get('variacao_externa_id') or ''))].add(a['produto_id'])
        for c in costs:
            at = local_time(c['valid_from'])
            if at:
                self.costs[c['produto_id']].append((at, c))
        for values in self.costs.values():
            values.sort(key=lambda pair: pair[0])
        for alias in aliases or []:
            if not alias.get('aprovado') or not alias.get('produto_id'):
                continue
            code = str(alias.get('normalizado') or alias.get('codigo_externo') or '').strip().casefold()
            if code:
                key = (alias.get('integration_id'), str(alias.get('plataforma') or '').casefold(),
                       str(alias.get('tipo') or 'SKU').upper(), code)
                self.aliases[key].add(alias['produto_id'])

    def resolve(self, item, account, platform=None):
        direct = item.get('produto_id')
        sku = str(item.get('sku_externo') or '').strip().casefold()
        platform_key = str(platform or '').casefold()
        candidates = self.skus[sku] | self.listings[
            (account, str(item.get('item_externo_id') or ''), str(item.get('variacao_externa_id') or ''))]
        if sku:
            candidates |= self.aliases[(account, platform_key, 'SKU', sku)]
            candidates |= self.aliases[(None, platform_key, 'SKU', sku)]
        if direct in self.products and not self._is_model(self.products[direct]):
            candidates.add(direct)
        candidates = {product_id for product_id in candidates
                      if product_id in self.products and not self._is_model(self.products[product_id])}
        unit = self.listing_unit(item, account)
        if unit and unit.get('origem_vinculo') in {'manual','confirmado'}:
            confirmed = unit.get('produto_id')
            if confirmed in self.products and not self._is_model(self.products[confirmed]):
                return self.products[confirmed], 'confirmed_conflict' if candidates - {confirmed} else 'manual'
        if len(candidates) == 1:
            product_id = next(iter(candidates))
            return self.products[product_id], 'direct' if product_id == direct else 'matched'
        return {}, 'conflict' if candidates else 'unmapped'

    @staticmethod
    def _is_model(product):
        return product.get('papel_catalogo') == 'modelo' or (
            product.get('papel_catalogo') is None and product.get('formato') == 'com_variacao')

    def listing_unit(self, item, account):
        return self.listing_units.get((account, str(item.get('item_externo_id') or ''),
                                      str(item.get('variacao_externa_id') or '')))

    def cost(self, product, sold_at):
        eligible = [c for at, c in self.costs[product.get('id')] if at <= sold_at]
        if eligible:
            c = eligible[-1]
            return number(c['unit_cost']), bool(c['estimated']), c['source']
        # Never present today's price as an observed historical cost.
        return number(product.get('preco_custo')), True, 'cadastro_atual_reconstruido'


def item_group(item):
    listing = str(item.get('listing') or '').strip()
    if listing:
        return f"listing:{listing}:variation:{item.get('variation') or ''}"
    sku = str(item.get('sku') or '').strip().lower()
    return f'sku:{sku}' if sku else 'unidentified'


def preserve_item_attribution(projection, previous_facts, catalog):
    """Ordinary refreshes update sales, while explicit review owns attribution."""
    by_group = {fact['chave_grupo']:fact for fact in previous_facts}
    for item in projection.get('items') or []:
        fact = by_group.get(item_group(item))
        if fact is None:
            continue
        product = catalog.products.get(fact.get('produto_id')) or {}
        item.update(product_id=fact.get('produto_id'),mapping=fact['origem_atribuicao'],
                    announcement_id=fact.get('anuncio_id'),listing_unit_id=fact.get('unidade_anuncio_id'),
                    family_id=product.get('parent_id') or product.get('id'),
                    family_name=(catalog.products.get(product.get('parent_id')) or product).get('nome'),
                    category_id=product.get('categoria_id'),format=product.get('formato'))
        item['name'] = product.get('nome') or item.get('listing_title') or 'Não identificado'
        cost, estimated, source = catalog.cost(product,local_time(projection['sold_at']))
        item.update(unit_cost=cost,cost_estimated=estimated,cost_source=source)
    return projection


def project(source, catalog):
    order = source['order']
    from nistiprint_shared.services.platform_drivers.insights_registry import extract
    insights = extract(source)
    facts = insights.facts
    marketplace = str(order.get('marketplace_module_id') or order.get('origem') or 'desconhecido').lower()
    account = order.get('marketplace_integration_id')
    sold_at = local_time(order.get('data_compra_marketplace') or order.get('data_venda') or order.get('created_at'))
    if sold_at is None:
        raise ValueError(f"Pedido {order['id']} sem data válida")
    # Precision is supported by raw evidence, not a fabricated midnight timestamp.
    provider_date = facts.get('sold_at')
    precise = provider_date not in (None, '', 0, '0') and local_time(provider_date) is not None
    if precise:
        sold_at = local_time(provider_date)
    stage = order.get('marketplace_lifecycle_stage')
    if not stage or stage == 'unknown':
        stage = facts.get('stage','unknown')
    paid = local_time(order.get('data_pagamento_marketplace'))
    payment_status = str(order.get('marketplace_payment_status') or '').lower()
    if payment_status in {'refunded','fully_refunded','full_refund'}:
        stage = 'refunded'
    eligible = stage in {'paid_preparation', 'documentation_ready', 'fulfillment_ready', 'shipped',
                         'shipping_exception', 'delivered', 'partially_refunded'}
    if stage == 'unknown' and paid:
        eligible = True
    buyer = facts.get('buyer_id')
    buyer_key = hashlib.sha256(f'{marketplace}:{account}:{buyer}'.encode()).hexdigest() if buyer and account is not None else None
    region, city = facts.get('region'), facts.get('city')
    items = []
    for ip in source.get('items') or []:
        product, mapping = catalog.resolve(ip, account, marketplace)
        listing_unit = catalog.listing_unit(ip, account)
        cost, estimated, cost_source = catalog.cost(product, sold_at)
        items.append({
            'id': ip['id'], 'product_id': product.get('id'), 'mapping': mapping,
            'name': product.get('nome') or ip.get('titulo_anuncio') or ip.get('descricao') or 'Sem descrição',
            'listing_title': ip.get('titulo_anuncio') or ip.get('descricao'),
            'sku': ip.get('sku_externo'), 'listing': ip.get('item_externo_id'),
            'listing_unit_id': (listing_unit or {}).get('id'),
            'announcement_id': (listing_unit or {}).get('anuncio_id'),
            'variation': ip.get('variacao_externa_id'), 'variation_name': ip.get('variacao_externa'),
            'family_id': product.get('parent_id') or product.get('id'),
            'family_name': (catalog.products.get(product.get('parent_id')) or product).get('nome'),
            'category_id': product.get('categoria_id'), 'format': product.get('formato'),
            'quantity': number(ip.get('quantidade')), 'unit_price': number(ip.get('preco_unitario')),
            'subtotal': number(ip.get('subtotal')), 'unit_cost': cost,
            'cost_estimated': estimated, 'cost_source': cost_source,
        })
    names = []
    for n in source.get('names') or []:
        name = n.get('customization_name')
        initial = n.get('customization_initial')
        metadata = n.get('metadata') or {}
        names.append({
            'id': f"{n['provider']}:{n['id']}", 'item_id': n.get('item_pedido_id'),
            'name': ' '.join(str(name).split()) if name else None,
            'initial': ' '.join(str(initial).split()) if initial else None,
            'quantity': number(n.get('quantity_to_personalize') or metadata.get('quantity_to_personalize')),
            'status': n.get('status'), 'confirmed': bool(n.get('confirmed') or metadata.get('confirmed')),
        })
    return {
        'insights': {k:v for k,v in insights.to_dict().items() if k!='facts'}, 'id': order['id'], 'generation': source['generation'], 'number': order.get('numero_pedido'),
        'account_id': account, 'account_name': source.get('account_name') or str(account or 'Sem conta'),
        'marketplace': marketplace, 'pack_id': order.get('pack_id'),
        'sold_on': sold_at.date().isoformat(), 'sold_at': sold_at.isoformat(),
        'hour': sold_at.hour if precise else None, 'weekday': sold_at.weekday(),
        'stage': stage, 'payment_status':payment_status, 'eligible': eligible, 'paid_at': paid.isoformat() if paid else None,
        'total': number(order.get('total_pedido')), 'currency': order.get('currency') or order.get('moeda') or facts.get('currency'),
        'buyer_key': buyer_key,
        'region': region, 'city': city, 'personalized': bool(order.get('personalizado')),
        'logistics': order.get('modalidade_logistica') or order.get('servico_logistico'),
        'shipped_at': order.get('despachado_em') or order.get('data_envio_marketplace'),
        'deadline': order.get('data_limite_envio'), 'items': items, 'names': names,
        'finance': source.get('finance'), 'events': source.get('events') or [],
    }
