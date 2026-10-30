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
        if type(payload.get('expected_version')) is not int or payload['expected_version'] < 1:
            raise ValueError('expected_version é obrigatório.')
        axes, variants, deactivate = payload.get('eixos'), payload.get('variacoes'), payload.get('inativar_ids', [])
        if not isinstance(axes, list) or not isinstance(variants, list) or not isinstance(deactivate, list):
            raise ValueError('Eixos, variações e inativar_ids devem ser listas.')
        variants = self._normalize_variants(variants)
        axes, variants = self._canonicalize_axis_names(axes, variants)
        arguments = {
            'p_produto_pai_id': int(product_id), 'p_expected_version': payload['expected_version'],
            'p_eixos': axes, 'p_variacoes': variants, 'p_inativar_ids': deactivate,
            'p_usuario': None if isinstance(user_id, int) else user_id,
        }
        if isinstance(user_id, int):
            arguments['p_actor'] = user_id
        result = self.db.rpc('catalogo_salvar_familia', arguments).execute().data
        return result

    def _canonicalize_axis_names(self, axes, variants):
        """Reuse axes/options whose canonical codes differ only in name case.

        SQL codes use lower(trim(name)); its unique name keys remain case
        sensitive. Resolve the existing spelling before the transactional RPC.
        """
        existing = self.db.table('produto_eixos').select('id,nome').execute().data or []
        by_name = {str(row['nome']).strip().lower(): row for row in existing}
        by_id = {row['id']: row for row in existing}
        normalized, names, options_by_name = [], {}, {}
        for axis in axes:
            entry = dict(axis)
            original_name = entry.get('nome') or entry.get('name')
            found = by_id.get(entry.get('eixo_id')) or by_name.get(str(original_name or '').strip().lower())
            if found:
                entry['eixo_id'] = found['id']
                entry['nome'] = found['nome']
                names[str(original_name or found['nome']).strip().lower()] = found['nome']
                options = self.db.table('produto_eixo_opcoes').select('id,nome').eq('eixo_id', found['id']).execute().data or []
                canonical = {str(row['nome']).strip().lower(): row['nome'] for row in options}
                options_by_name[found['nome']] = canonical
                for field in ('opcoes', 'options'):
                    if isinstance(entry.get(field), list):
                        entry[field] = [canonical.get(value.strip().lower(), value) if isinstance(value, str) else value for value in entry[field]]
            normalized.append(entry)
        remapped = []
        for variant in variants:
            entry = dict(variant)
            if isinstance(entry.get('variation_values'), dict):
                values = {}
                for name, value in entry['variation_values'].items():
                    canonical_name = names.get(str(name).strip().lower(), name)
                    choices = options_by_name.get(canonical_name, {})
                    values[canonical_name] = choices.get(value.strip().lower(), value) if isinstance(value, str) else value
                entry['variation_values'] = values
            remapped.append(entry)
        return normalized, remapped

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
            for legacy, canonical in {'name':'nome','description':'descricao','price':'preco_venda',
                                      'cost_price':'preco_custo','category_id':'categoria_id',
                                      'stock_min':'estoque_minimo','stock_max':'estoque_maximo'}.items():
                if legacy in item and canonical not in item:
                    item[canonical] = item[legacy]
            result.append(item)
        return result
