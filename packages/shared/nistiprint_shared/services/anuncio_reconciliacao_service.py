"""Deterministic current listing reconciliation, independent of historical facts."""
from collections import defaultdict


def normalized(value):
    return str(value or '').strip().lower()


def resolve_unit(unit, products, aliases):
    sku = normalized(unit.get('sku_externo'))
    direct = {p['id'] for p in products if p.get('papel_catalogo') != 'modelo' and normalized(p.get('sku')) == sku} if sku else set()
    alias = {a['produto_id'] for a in aliases if a.get('aprovado') is True
             and a.get('integration_id') == unit['integration_id']
             and normalized(a.get('normalizado') or a.get('codigo_externo')) == sku} if sku else set()
    candidates = direct | alias
    pending_alias = any(a.get('integration_id') == unit['integration_id']
                        and normalized(a.get('normalizado') or a.get('codigo_externo')) == sku
                        and a.get('aprovado') is not True for a in aliases) if sku else False
    confirmed = unit.get('produto_id') if unit.get('origem_vinculo') in {'manual', 'confirmado'} else None
    if confirmed:
        return confirmed, 'confirmed_conflict' if candidates - {confirmed} or pending_alias else 'confirmed', sorted(candidates)
    if pending_alias:
        return None, 'alias_pending', sorted(candidates)
    if len(candidates) > 1:
        return None, 'conflict', sorted(candidates)
    if len(candidates) == 1:
        return next(iter(candidates)), 'sku' if direct else 'alias', sorted(candidates)
    return None, 'unmapped', []


class AnuncioReconciliacaoService:
    def __init__(self, db):
        self.db = db

    def reconcile(self, account_id, item_ids):
        if not item_ids:
            return {'processed': 0}
        units = self.db.table('produto_anuncios').select('*').eq('integration_id', account_id).in_('item_externo_id', item_ids).execute().data or []
        skus = list({normalized(u.get('sku_externo')) for u in units if normalized(u.get('sku_externo'))})
        # Product pagination avoids PostgREST's default row ceiling.
        products = []
        for offset in range(0, 1000000, 500):
            batch = self.db.table('produtos').select('id,sku,papel_catalogo').order('id').range(offset, offset + 499).execute().data or []
            products.extend(batch)
            if len(batch) < 500:
                break
        aliases = self.db.table('produtos_externos').select('produto_id,integration_id,normalizado,codigo_externo,aprovado,tipo').eq('integration_id', account_id).in_('normalizado', skus).execute().data or [] if skus else []
        aliases = [a for a in aliases if (a.get('tipo') or 'SKU').upper() == 'SKU']
        valid_products = {p['id'] for p in products if p.get('papel_catalogo') != 'modelo'}
        aliases = [a if a['produto_id'] in valid_products else dict(a, aprovado=False) for a in aliases]
        counts = defaultdict(int)
        for unit in units:
            product_id, reason, candidates = resolve_unit(unit, products, aliases)
            self.db.rpc('marketplace_anuncio_reconciliar', {
                'p_account': account_id, 'p_unit': unit['id'], 'p_version': unit.get('vinculo_versao', 1),
                'p_product': product_id, 'p_reason': reason, 'p_candidates': candidates,
            }).execute()
            counts[reason] += 1
        return {'processed': len(units), 'results': dict(counts)}
