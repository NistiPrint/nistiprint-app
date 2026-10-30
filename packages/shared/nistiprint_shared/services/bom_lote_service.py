"""Server-side orchestration for batch BOM edits."""
import hashlib
import json

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_lote_planejamento import planejar_composicao


class BomLoteService:
    def _products(self, ids):
        ids = sorted({int(value) for value in ids})
        if not ids or len(ids) > 100:
            raise ValueError('BOM_BATCH_SIZE: selecione de 1 a 100 produtos.')
        response = supabase_db.table('produtos').select(
            'id,sku,nome,tipo_material,formato,estrutura,parent_id,herdar_bom_pai,status,unidade_medida_id'
        ).in_('id', ids).execute()
        products = {int(row['id']): row for row in response.data or []}
        if len(products) != len(ids):
            raise ValueError('BOM_PRODUCT_NOT_FOUND')
        unit_ids = sorted({int(row['unidade_medida_id']) for row in products.values() if row.get('unidade_medida_id')})
        units = {}
        if unit_ids:
            unit_rows = supabase_db.table('unidades_medida').select('id,abreviacao').in_('id', unit_ids).execute().data or []
            units = {int(row['id']): row.get('abreviacao') for row in unit_rows}
        for row in products.values():
            row['unidade_medida'] = units.get(int(row['unidade_medida_id'])) if row.get('unidade_medida_id') else None
        return products

    @staticmethod
    def _token(product, lines):
        content = {'product': product, 'lines': sorted(lines, key=lambda row: int(row['componente_id']))}
        raw = json.dumps(content, sort_keys=True, separators=(',', ':'), default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def consulta(self, ids, componente_ids=None):
        products = self._products(ids)
        effective = bom_service.get_bom_for_multiple_products(list(products))
        effective_line_ids = sorted({
            int(item.line_id) for lines in effective.values() for item in lines if item.line_id is not None
        })
        persisted_groups = {}
        if effective_line_ids:
            persisted = supabase_db.table('ficha_tecnica').select('id,grupo').in_('id', effective_line_ids).execute().data or []
            persisted_groups = {int(row['id']): row.get('grupo') for row in persisted}
        rows = {}
        tokens = {}
        for product_id, product in products.items():
            lines = [
                {'componente_id': int(item.componente_id), 'quantidade_necessaria': str(item.quantidade),
                 'unidade_medida': item.unit, 'is_inherited': item.is_inherited,
                 'grupo': item.group,
                 'grupo_persistido': persisted_groups.get(int(item.line_id)) if item.line_id is not None else None,
                 'line_id': item.line_id, 'produto_pai_id': item.produto_pai_id}
                for item in effective.get(product_id, [])
            ]
            rows[str(product_id)] = sorted(lines, key=lambda row: int(row['componente_id']))
            tokens[str(product_id)] = self._token(product, lines)
        selected_components = sorted({int(value) for value in (componente_ids or [])})
        if len(selected_components) > 100:
            raise ValueError('BOM_BATCH_SIZE: selecione até 100 componentes.')
        components = self._products(selected_components) if selected_components else {}
        return {'produtos': list(products.values()), 'composicoes': rows, 'componentes': list(components.values()), 'tokens': tokens}

    def previa(self, produto_ids, operacoes, tokens):
        if len(operacoes) > 5000:
            raise ValueError('BOM_BATCH_SIZE: o lote aceita até 5.000 células editadas.')
        consulta = self.consulta(produto_ids)
        return self._preview_snapshot(produto_ids, operacoes, tokens, consulta['composicoes'], consulta['produtos'])

    def _preview_snapshot(self, produto_ids, operacoes, tokens, compositions, products):
        if not isinstance(operacoes, list) or len(operacoes) > 5000:
            raise ValueError('BOM_BATCH_SIZE: o lote aceita até 5.000 células editadas.')
        products_by_id = {str(row['id']): row for row in products}
        snapshot_tokens = {}
        result = {}
        for pid in map(int, produto_ids):
            key = str(pid)
            if key not in compositions or key not in products_by_id:
                raise ValueError('BOM_PRODUCT_NOT_FOUND')
            snapshot_tokens[key] = self._token(products_by_id[key], compositions[key])
            if tokens.get(key) != snapshot_tokens[key]:
                raise RuntimeError('BOM_CONFLICT')
            ops = [row for row in operacoes if int(row.get('produto_id', 0)) == pid]
            result[key] = planejar_composicao(compositions[key], ops)
        if any(int(row.get('produto_id', 0)) not in set(map(int, produto_ids)) for row in operacoes):
            raise ValueError('BOM_INVALID_OPERATION')
        revision = hashlib.sha256(json.dumps({'tokens': snapshot_tokens, 'result': result}, sort_keys=True).encode()).hexdigest()
        return {
            'revisao': revision, 'composicoes': result, 'tokens': snapshot_tokens,
            'composicoes_anteriores': compositions, 'produtos': products,
        }

    def aplicar(self, produto_ids, operacoes, tokens, revision, idempotency_key, user_id,
                expected_compositions, expected_products):
        if not isinstance(idempotency_key, str) or len(idempotency_key) < 16 or len(idempotency_key) > 128:
            raise ValueError('BOM_IDEMPOTENCY_KEY_INVALID')
        preview = self._preview_snapshot(
            produto_ids, operacoes, tokens, expected_compositions,
            list(expected_products.values()) if isinstance(expected_products, dict) else expected_products,
        )
        if preview['revisao'] != revision:
            raise RuntimeError('BOM_REVIEW_CONFLICT')
        response = supabase_db.rpc('aplicar_composicao_lote', {
            'p_produto_ids': list(map(int, produto_ids)), 'p_operacoes': operacoes,
            'p_tokens': tokens, 'p_expected_composicoes': expected_compositions,
            'p_expected_products': {str(row['id']): row for row in preview['produtos']},
            'p_revisao': revision, 'p_idempotency_key': idempotency_key,
            'p_usuario_id': int(user_id),
        }).execute()
        return response.data


bom_lote_service = BomLoteService()
