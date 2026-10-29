"""Read-only projection of active demand onto production stock.

The projection never reserves stock. Actual allocation remains in the demand
stock workflow; this module only explains what would be covered in priority order.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation


STAGE_FIELDS = {
    'miolo': 'miolos_prontos_retirada_qtd',
    'capa': 'capas_impressas_qtd',
    'capa_acabada': 'capas_produzidas_qtd',
}
ROLE_FIELDS = {
    'MIOLO': 'miolos_prontos_retirada_qtd',
    'CAPA_IMPRESSAO': 'capas_impressas_qtd',
    'CAPA_ACABADA': 'capas_produzidas_qtd',
}


def _number(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _as_float(value):
    return float(value)


def _unmapped_entry(demanda, item, pending, reason):
    miolo_nome = (item.get('miolo_chave') or item.get('miolo_nome') or item.get('miolo_name')
                  or item.get('produto_miolo_nome') or item.get('nome_miolo'))
    sku = item.get('sku') or item.get('sku_externo')
    if not miolo_nome and sku:
        # Match the Torre/Escopo rule: use the first ten SKU characters and
        # apply the shared legacy miolo corrections (CADMNA -> VACMNA, etc.).
        from nistiprint_shared.utils import apply_miolo_fixes
        miolo_nome = apply_miolo_fixes(str(sku)[:10])
    return {
        'demanda_id': demanda['id'],
        'demanda_nome': demanda.get('nome') or demanda.get('descricao') or f'Demanda {demanda["id"]}',
        'item_id': item.get('id'),
        'item_nome': item.get('item_descricao') or item.get('descricao') or item.get('sku') or 'Item sem nome',
        'simulacao': bool(demanda.get('simulacao')),
        'motivo': reason,
        # Informações opcionais para exibição; não entram nos totais do produto.
        'miolo_nome': miolo_nome,
        'miolo_key': miolo_nome,
        'sku': sku,
        'pendente': _as_float(pending),
        'data_entrega': demanda.get('data_entrega'),
        'horario_coleta': demanda.get('horario_coleta'),
        'prioridade': _as_float(_number(demanda.get('prioridade_manual') or demanda.get('manual_priority_score'))),
    }


def components_for_product(product_id, target_ids, nodes):
    """Return target components and their per-unit BOM quantities."""
    found = defaultdict(Decimal)

    def visit(current_id, factor, path):
        key = str(current_id)
        if key in path:
            raise ValueError(f'Ficha de materiais circular no produto {product_id}')
        if key in target_ids:
            found[key] += factor
            return
        for line in (nodes.get(key) or {}).get('componentes') or []:
            child_id = str(line['componente_id'])
            quantity = _number(line.get('quantidade_necessaria'))
            if quantity <= 0:
                raise ValueError(f'Quantidade inválida na ficha do produto {product_id}')
            visit(child_id, factor * quantity, path | {key})

    visit(product_id, Decimal(1), set())
    return found


def prepare_component_distributions(product_id, role, distributions, items_by_id, graph):
    """Validate reservations in component units and derive item-stage units."""
    if role not in ROLE_FIELDS:
        return distributions
    prepared = []
    nodes = (graph or {}).get('nodes') or {}
    for dist in distributions:
        item = items_by_id.get(str(dist.get('item_id')))
        if not item:
            raise ValueError('Item da demanda não encontrado para a alocação.')
        quantity = _number(dist.get('quantidade'))
        if quantity <= 0:
            raise ValueError('Quantidade de alocação inválida.')
        root_id = item.get('produto_id')
        factors = components_for_product(root_id, {str(product_id)}, nodes) if root_id else {}
        factor = factors.get(str(product_id))
        if role == 'MIOLO' and item.get('id_produto_miolo') and str(item['id_produto_miolo']) != str(product_id):
            raise ValueError(f'Miolo da demanda diverge do produto {product_id}.')
        if not factor and role == 'MIOLO' and str(item.get('id_produto_miolo')) == str(product_id):
            factor = Decimal(1)
        if not factor:
            raise ValueError(f'Produto {product_id} não está vinculado ao item {item["id"]} nesta etapa.')
        stage_quantity = quantity / factor
        prepared.append({**dist, 'quantidade_estagio': _as_float(stage_quantity)})
    return prepared


def build_production_demand_plan(tipo, products, demandas, items_by_demanda, graph, stage_product_ids=None, horizonte=None, data_referencia=None):
    """Build product totals and a per-demand forecast from already fetched data."""
    if tipo not in STAGE_FIELDS:
        raise ValueError('Tipo de planejamento inválido')

    product_map = {str(p['id']): p for p in products}
    target_ids = {str(value) for value in stage_product_ids} if stage_product_ids is not None else set(product_map)
    nodes = (graph or {}).get('nodes') or {}
    entries = defaultdict(list)
    unmapped = []
    stage_field = STAGE_FIELDS[tipo]

    if horizonte:
        from datetime import date as _date
        reference = _date.fromisoformat(data_referencia) if data_referencia else _date.today()
        def bucket(demanda):
            due = demanda.get('data_entrega')
            if not due:
                return 'sem_prazo'
            due = _date.fromisoformat(str(due)[:10])
            return 'atrasado' if due < reference else 'hoje' if due == reference else 'amanha' if (due-reference).days == 1 else 'depois'
        demandas = [d for d in demandas if bucket(d) in horizonte]

    for demanda in demandas:
        demand_id = str(demanda['id'])
        for item in items_by_demanda.get(demand_id, []) or []:
            total = _number(item.get('quantidade_total', item.get('quantidade')))
            pending = max(Decimal(0), total - _number(item.get(stage_field)))
            if pending <= 0:
                continue
            item_product_id = item.get('produto_id')
            components = components_for_product(item_product_id, target_ids, nodes) if item_product_id else {}
            explicit_miolo_id = str(item.get('id_produto_miolo') or '')
            if tipo == 'miolo' and explicit_miolo_id and components and explicit_miolo_id not in components:
                unmapped.append(_unmapped_entry(
                    demanda, item, pending, 'Miolo informado na demanda diverge da ficha de materiais'))
                continue
            if tipo == 'miolo' and not components:
                if explicit_miolo_id in target_ids:
                    components = {explicit_miolo_id: Decimal(1)}
            if len(components) > 1:
                unmapped.append(_unmapped_entry(
                    demanda, item, pending,
                    'Mais de um produto da etapa na ficha; o progresso do item não identifica qual componente já foi atendido'))
                continue
            if any(component_id not in product_map for component_id in components):
                unmapped.append(_unmapped_entry(
                    demanda, item, pending,
                    'Produto da etapa está inativo ou indisponível no controle de estoque'))
                continue
            if not components:
                unmapped.append(_unmapped_entry(
                    demanda, item, pending,
                    'Produto da etapa ausente ou sem vínculo confiável na ficha de materiais'))
                continue
            for component_id, factor in components.items():
                entries[component_id].append({
                    'demanda_id': demanda['id'],
                    'demanda_nome': demanda.get('nome') or demanda.get('descricao') or f'Demanda {demanda["id"]}',
                    'item_id': item.get('id'),
                    'item_nome': item.get('item_descricao') or item.get('descricao') or item.get('sku') or 'Item sem nome',
                    'simulacao': bool(demanda.get('simulacao')),
                    'data_entrega': demanda.get('data_entrega'),
                    'horario_coleta': demanda.get('horario_coleta'),
                    'prioridade': _number(demanda.get('prioridade_manual') or demanda.get('manual_priority_score')),
                    'fator': factor,
                    'pendente': pending * factor,
                })

    planned = []
    for product_id, product in product_map.items():
        stock = product.get('stock_details') or {}
        available = max(Decimal(0), _number(stock.get('quantidade_disponivel')))
        minimum = max(Decimal(0), _number(product.get('stock_min')))
        remaining_stock = available
        demand_rows = []
        ordered_entries = sorted(entries[product_id], key=lambda row: (
            -row['prioridade'], row['data_entrega'] or '9999-12-31', row['horario_coleta'] or '23:59',
            str(row['demanda_id']), str(row['item_id']),
        ))
        for entry in ordered_entries:
            covered = min(remaining_stock, entry['pendente'])
            remaining_stock -= covered
            demand_rows.append({
                **{key: value for key, value in entry.items() if key not in ('prioridade', 'fator', 'pendente')},
                'prioridade': _as_float(entry['prioridade']),
                'fator': _as_float(entry['fator']),
                'pendente': _as_float(entry['pendente']),
                'coberto_estoque': _as_float(covered),
                'falta_apos_estoque': _as_float(entry['pendente'] - covered),
            })
        pending_total = sum((entry['pendente'] for entry in ordered_entries), Decimal(0))
        demand_shortage = max(Decimal(0), pending_total - available)
        replenishment = max(Decimal(0), minimum - max(Decimal(0), available - pending_total))
        planned.append({
            'product_id': product['id'],
            'name': product.get('name') or product.get('nome'),
            'sku': product.get('sku'),
            'estoque_fisico': _as_float(_number(stock.get('quantidade'))),
            'estoque_reservado': _as_float(_number(stock.get('quantidade_reservada'))),
            'estoque_disponivel': _as_float(available),
            'estoque_minimo': _as_float(minimum),
            'demanda_pendente': _as_float(pending_total),
            'coberto_estoque': _as_float(min(available, pending_total)),
            'falta_demandas': _as_float(demand_shortage),
            'reposicao_minimo': _as_float(replenishment),
            'demandas': demand_rows,
        })
    planned.sort(key=lambda row: (-row['falta_demandas'], row['name'] or '', str(row['product_id'])))
    return {'products': planned, 'unmapped': unmapped}
