"""Account-scoped listing reads and audited unit reconciliation."""


class AnuncioService:
    def __init__(self, db):
        self.db = db

    def list(self, *, page=1, per_page=50, integration_id=None, produto_id=None, status=None, query=None):
        page, per_page = max(1, int(page)), min(100, max(1, int(per_page)))
        if produto_id is not None:
            linked = self.db.table('produto_anuncios').select('anuncio_id').eq('produto_id', int(produto_id)).execute().data or []
            announcement_ids = list({row['anuncio_id'] for row in linked if row.get('anuncio_id') is not None})
            if not announcement_ids:
                return {'rows': [], 'page': page, 'per_page': per_page, 'total': 0}
        else:
            announcement_ids = None
        q = self.db.table('marketplace_anuncios').select('*', count='exact').order('id', desc=True)
        if integration_id:
            q = q.eq('integration_id', int(integration_id))
        if announcement_ids is not None:
            q = q.in_('id', announcement_ids)
        if status:
            q = q.eq('situacao_normalizada', status)
        if query:
            # Use a provider-neutral text filter; callers cannot inject PostgREST syntax.
            safe = str(query).replace('%', '').replace('*', '').strip()[:100]
            if safe:
                q = q.ilike('titulo', f'%{safe}%')
        start = (page - 1) * per_page
        result = q.range(start, start + per_page - 1).execute()
        headers = result.data or []
        ids = [row['id'] for row in headers]
        units = self.db.table('produto_anuncios').select('*').in_('anuncio_id', ids).order('id').execute().data or [] if ids else []
        units_by_header = {}
        for unit in units:
            units_by_header.setdefault(unit.get('anuncio_id'), []).append(unit)
        for header in headers:
            header['unidades'] = units_by_header.get(header['id'], [])
        return {'rows': headers, 'page': page, 'per_page': per_page, 'total': result.count or 0}

    def get(self, announcement_id):
        rows = self.db.table('marketplace_anuncios').select('*').eq('id', announcement_id).limit(1).execute().data or []
        if not rows:
            return None
        header = rows[0]
        header['unidades'] = self.db.table('produto_anuncios').select('*').eq('anuncio_id', announcement_id).order('id').execute().data or []
        return header

    def for_product(self, product_id):
        units = self.db.table('produto_anuncios').select('*').eq('produto_id', product_id).order('id', desc=True).execute().data or []
        ids = list({unit.get('anuncio_id') for unit in units if unit.get('anuncio_id') is not None})
        headers = self.db.table('marketplace_anuncios').select('*').in_('id', ids).execute().data or [] if ids else []
        by_id = {header['id']: header for header in headers}
        grouped = {}
        for unit in units:
            if unit.get('anuncio_id') is not None:
                grouped.setdefault(unit['anuncio_id'], []).append(unit)
        for header in headers:
            header['unidades'] = grouped.get(header['id'], [])
        return {'anuncios': headers, 'unidades_sem_cabecalho': [u for u in units if u.get('anuncio_id') is None]}
