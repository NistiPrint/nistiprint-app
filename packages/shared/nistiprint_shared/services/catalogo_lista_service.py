"""Family pagination and batched product list projections."""
import math
from urllib.parse import urlsplit


def image_url(product):
    for value in (product.get('atributos') or {}).get('images', []) or []:
        url = value if isinstance(value, str) else value.get('url') if isinstance(value, dict) else None
        try:
            parsed = urlsplit(url or '')
            if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password:
                return url
        except ValueError:
            pass
    return None


class CatalogoListaService:
    def __init__(self, db):
        self.db = db

    def list(self, *, page, per_page, q='', category_id='', status='', material_type='', setor_id='', **unused):
        # Read in bounded pages, including children, before paginating families.
        # This also handles a matching child whose parent fails the filters.
        rows, offset = [], 0
        while True:
            batch = self.db.table('produtos').select('*').is_('atributos->>catalog_merged_into', 'null').order('id').range(offset, offset + 499).execute().data or []
            rows.extend(batch)
            if len(batch) < 500:
                break
            offset += 500
        def matches(row, text=True):
            return (not text or not q or q.casefold() in str(row.get('nome', '')).casefold() or q.casefold() in str(row.get('sku', '')).casefold()) and all(
                not expected or str(row.get(field)) == str(expected)
                for field, expected in [('categoria_id', category_id), ('status', status), ('tipo_material', material_type), ('setor_responsavel_id', None if setor_id == 'null' else setor_id)]
            ) and (setor_id != 'null' or row.get('setor_responsavel_id') is None)
        children = {}
        for row in rows:
            if row.get('parent_id'):
                children.setdefault(row['parent_id'], []).append(row)
        roots = []
        for row in reversed(rows):
            if row.get('parent_id'):
                continue
            variants = children.get(row['id'], [])
            root_matches = matches(row)
            matching = [child for child in variants if matches(child, text=not root_matches)]
            if not root_matches and not matching:
                continue
            row['variants'] = matching
            row['has_variants'] = bool(variants)
            row['expand_variants'] = bool(matching) and not root_matches
            roots.append(row)
        total_pages = max(1, math.ceil(len(roots) / per_page))
        roots = roots[(page - 1) * per_page:page * per_page]
        visible = [p for root in roots for p in [root, *root['variants']]]
        ids = [row['id'] for row in visible]
        units = self.db.table('produto_anuncios').select('produto_id,anuncio_id').in_('produto_id',ids).order('id').execute().data or [] if ids else []
        announcement_ids = list({unit['anuncio_id'] for unit in units if unit.get('anuncio_id')})
        headers = self.db.table('marketplace_anuncios').select('id,imagem_comercial').in_('id',announcement_ids).execute().data or [] if announcement_ids else []
        images = {row['id']:image_url({'atributos':{'images':[row.get('imagem_comercial')]}}) for row in headers}
        fallback = {}
        for unit in units:
            if images.get(unit.get('anuncio_id')):
                fallback.setdefault(unit['produto_id'],images[unit['anuncio_id']])
        for row in visible:
            row['imagem_principal'] = image_url(row) or fallback.get(row['id'])
        for root in roots:
            root['imagem_principal'] = root['imagem_principal'] or next((image_url(child) for child in children.get(root['id'], []) if image_url(child)), None)
        return roots, total_pages
