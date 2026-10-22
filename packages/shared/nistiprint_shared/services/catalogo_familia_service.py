"""Application service for canonical product families."""


class CatalogoFamiliaService:
    def __init__(self, db):
        self.db = db

    def get(self, product_id):
        parents = self.db.table('produtos').select('*').eq('id', product_id).limit(1).execute().data or []
        if not parents:
            return None
        parent = parents[0]
        axes = self.db.table('produto_pai_eixos').select('*').eq('produto_pai_id', product_id).order('posicao').execute().data or []
        for axis in axes:
            axis_id = axis['eixo_id']
            axis_rows = self.db.table('produto_eixos').select('*').eq('id', axis_id).limit(1).execute().data or []
            allowed = self.db.table('produto_pai_eixo_opcoes').select('opcao_id').eq('produto_pai_id', product_id).eq('eixo_id', axis_id).execute().data or []
            options = []
            for row in allowed:
                option_rows = self.db.table('produto_eixo_opcoes').select('*').eq('id', row['opcao_id']).limit(1).execute().data or []
                if option_rows:
                    options.append(option_rows[0])
            axis['eixo'] = axis_rows[0] if axis_rows else None
            axis['opcoes'] = options
        variants = self.db.table('produtos').select('*').eq('parent_id', product_id).order('id').execute().data or []
        values = self.db.table('produto_variacao_valores').select('*').in_('produto_id', [v['id'] for v in variants]).execute().data or [] if variants else []
        by_product = {}
        for value in values:
            by_product.setdefault(value['produto_id'], []).append(value)
        for variant in variants:
            variant['valores_catalogo'] = by_product.get(variant['id'], [])
        pending = self.db.table('produto_catalogo_pendencias').select('*').eq('produto_pai_id', product_id).is_('resolved_at', 'null').order('id').execute().data or []
        return {'produto': parent, 'eixos': axes, 'variacoes': variants,
                'pendencias': pending, 'catalogo_versao': parent.get('catalogo_versao', 1)}

    def save(self, product_id, payload, user_id=None):
        if not isinstance(payload, dict):
            raise ValueError('Envie um objeto JSON para salvar a família.')
        if not isinstance(payload.get('expected_version'), int):
            raise ValueError('expected_version é obrigatório.')
        axes, variants, deactivate = payload.get('eixos'), payload.get('variacoes'), payload.get('inativar_ids', [])
        if not isinstance(axes, list) or not isinstance(variants, list) or not isinstance(deactivate, list):
            raise ValueError('Eixos, variações e inativar_ids devem ser listas.')
        variants = self._normalize_variants(variants)
        result = self.db.rpc('catalogo_salvar_familia', {
            'p_produto_pai_id': int(product_id), 'p_expected_version': payload['expected_version'],
            'p_eixos': axes, 'p_variacoes': variants, 'p_inativar_ids': deactivate,
            'p_usuario': user_id,
        }).execute().data
        return result

    @staticmethod
    def _normalize_variants(variants):
        """Translate the legacy editor's row IDs without doing writes."""
        result = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError('Cada variação deve ser um objeto.')
            item = dict(variant)
            legacy_id = item.pop('id', None)
            if item.get('produto_id') is None and str(legacy_id or '').isdigit():
                item['produto_id'] = int(legacy_id)
            if 'variation_values' not in item and isinstance(item.get('atributos'), dict):
                item['variation_values'] = item['atributos'].get('variation_values', {})
            result.append(item)
        return result
