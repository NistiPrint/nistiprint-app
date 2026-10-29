"""Estado puro do roteiro de demanda. Nenhuma função deste módulo grava operações reais."""

from copy import deepcopy
from datetime import date, datetime, timezone
from uuid import uuid4


STAGES = (
    'capas_impressas_qtd', 'capas_produzidas_qtd', 'capas_prontas_retirada_qtd',
    'miolos_prontos_retirada_qtd', 'expedicao_capas_retiradas_qtd',
    'expedicao_miolos_retirados_qtd',
)
DEPENDENCIES = {
    'capas_produzidas_qtd': 'capas_impressas_qtd',
    'capas_prontas_retirada_qtd': 'capas_produzidas_qtd',
    'expedicao_capas_retiradas_qtd': 'capas_prontas_retirada_qtd',
    'expedicao_miolos_retirados_qtd': 'miolos_prontos_retirada_qtd',
}


def positive_int(value, label='Quantidade'):
    try:
        number = int(value)
        if isinstance(value, bool) or float(value) != number or number <= 0:
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'{label} deve ser um inteiro positivo') from None


def create_state(lines, orders, scope):
    if not isinstance(lines, list) or not 0 < len(lines) <= 1000:
        raise ValueError('Informe entre 1 e 1000 linhas')
    items = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValueError('Linha inválida')
        amount = positive_int(line.get('quantidade'), f'Quantidade da linha {index + 1}')
        items.append({
            'id': str(uuid4()), 'ordem': index + 1,
            'produto_id': line.get('produto_id'), 'id_produto_miolo': line.get('id_produto_miolo'),
            'item_descricao': str(line.get('produto') or '')[:500],
            'descricao': str(line.get('produto') or '')[:500],
            'sku': str(line.get('sku') or '')[:150],
            'variacao': str(line.get('variacao') or '')[:255],
            'miolo_name': str(line.get('miolo') or '')[:255],
            'miolo_nome': str(line.get('miolo') or '')[:255],
            'quantidade_total': amount, 'quantidade': amount,
            'status_item': 'Pendente', 'finalizados_qtd': 0,
            **{field: 0 for field in STAGES},
        })
    if not orders:
        raise ValueError('Nenhum pedido para simular')
    deadlines = sorted(str(order['data_limite_envio'])[:10] for order in orders if order.get('data_limite_envio'))
    return {
        'status': 'RASCUNHO', 'nome': f"Simulação · {scope.get('marketplace_nome') or 'Torre de Despacho'}",
        'canal_venda_nome': scope.get('marketplace_nome') or 'Torre de Despacho',
        'data_entrega': deadlines[0] if deadlines else date.today().isoformat(),
        'is_flex': any(order.get('is_flex') is True for order in orders),
        'itens': items, 'pedidos_origem': orders, 'coletas': [],
    }


PLANNING_STATUSES = ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL')
EXPEDITION_STATUSES = PLANNING_STATUSES + ('CONCLUIDO',)


def _active_rows(rows, statuses):
    return [row for row in rows or [] if (row.get('state') or {}).get('status') in statuses]


def simulation_demands(rows):
    """Simulações publicadas no formato (demanda, itens) do planejamento de insumos."""
    result = []
    for row in _active_rows(rows, PLANNING_STATUSES):
        state = row['state']
        demand = {
            'id': row['id'], 'nome': state.get('nome'), 'data_entrega': state.get('data_entrega'),
            'horario_coleta': None, 'prioridade_manual': 0, 'simulacao': True,
        }
        result.append((demand, state.get('itens') or []))
    return result


def simulation_consolidated(rows):
    """Itens das simulações no formato de view_consolidado_producao (expedição)."""
    result = []
    for row in _active_rows(rows, EXPEDITION_STATUSES):
        state = row['state']
        for item in state.get('itens') or []:
            covers = item.get('capas_prontas_retirada_qtd') or 0
            cores = item.get('miolos_prontos_retirada_qtd') or 0
            covers_out = item.get('expedicao_capas_retiradas_qtd') or 0
            cores_out = item.get('expedicao_miolos_retirados_qtd') or 0
            result.append({
                'item_id': item['id'], 'demanda_id': row['id'], 'demanda_nome': state.get('nome'),
                'data_entrega': state.get('data_entrega'), 'horario_coleta': None,
                'sku': item.get('sku'), 'item_nome': item.get('item_descricao'),
                'qtd_total': item.get('quantidade_total'),
                'capas_impressas_qtd': item.get('capas_impressas_qtd') or 0,
                'capas_prontas': covers, 'miolos_prontos': cores,
                'expedicao_capas_retiradas_qtd': covers_out,
                'expedicao_miolos_retirados_qtd': cores_out,
                'match_disponivel': min(covers - covers_out, cores - cores_out),
                'demanda_status': state.get('status'), 'status_item': item.get('status_item'),
                'trilha': 'FLEX' if state.get('is_flex') else 'NORMAL',
                'status_sincronia': None, 'simulacao': True,
            })
    return result


def display_state(row):
    state = deepcopy(row['state'])
    items = state['itens']
    total = sum(item['quantidade_total'] for item in items)
    finalized = sum(item['finalizados_qtd'] for item in items)
    state.update({
        'id': row['id'], 'simulacao': True, 'version': row['version'],
        'total_itens': total, 'total_quantidade': total,
        'itens_concluidos': finalized,
        'progresso_percentual': round(finalized * 100 / total) if total else 0,
        'quantidade_coletada_total': sum(c['quantidade'] for c in state['coletas']),
        'pedidos_origem_chunks': [], 'pedidos_origem_por_bling': [],
    })
    return state


def transition(current, action, payload):
    state = deepcopy(current)
    status = state['status']
    items = state['itens']
    total = sum(item['quantidade_total'] for item in items)
    collected = sum(c['quantidade'] for c in state['coletas'])
    if action == 'publicar':
        if status != 'RASCUNHO':
            raise ValueError('Somente rascunhos podem ser publicados na simulação')
        state['status'] = 'AGUARDANDO'
        return state
    if status == 'RASCUNHO':
        raise ValueError('Publique o cenário simulado antes de iniciar a produção')
    if status == 'COLETADO':
        raise ValueError('A simulação já foi totalmente coletada')
    if action == 'producao':
        updates = payload.get('updates')
        if not isinstance(updates, list) or not updates:
            raise ValueError('Informe os itens e as etapas de produção')
        seen = set()
        for update in updates:
            item = next((i for i in items if str(i['id']) == str(update.get('item_id'))), None)
            if not item or item['id'] in seen or item['status_item'] == 'Concluído':
                raise ValueError('Item inválido ou já concluído')
            seen.add(item['id'])
            deltas = update.get('producao_incremental')
            if not isinstance(deltas, dict) or not deltas or set(deltas) - set(STAGES):
                raise ValueError('Etapa de produção inválida')
            for field, raw_delta in deltas.items():
                delta = positive_int(raw_delta, 'Incremento')
                item[field] += delta
            for field in STAGES:
                if item[field] > item['quantidade_total']:
                    raise ValueError('Produção excede a quantidade do item')
            for field, dependency in DEPENDENCIES.items():
                if item[field] > item[dependency]:
                    raise ValueError('Etapa de produção excede a anterior')
            item['status_item'] = 'Em Andamento'
    elif action in ('finalizar_item', 'reverter_item'):
        item = next((i for i in items if str(i['id']) == str(payload.get('item_id'))), None)
        if not item:
            raise ValueError('Item não encontrado')
        if action == 'finalizar_item':
            quantity = positive_int(payload.get('quantidade'), 'Quantidade finalizada')
            if item['finalizados_qtd'] + quantity > item['quantidade_total']:
                raise ValueError('Finalização excede a quantidade restante')
            item['finalizados_qtd'] += quantity
            for field in STAGES:
                item[field] = max(item[field], item['finalizados_qtd'])
            item['status_item'] = 'Concluído' if item['finalizados_qtd'] == item['quantidade_total'] else 'Em Andamento'
        else:
            if collected or item['finalizados_qtd'] == 0:
                raise ValueError('Reversão indisponível após coleta ou sem finalização')
            item['finalizados_qtd'] = 0
            item['status_item'] = 'Em Andamento'
    elif action == 'finalizar_demanda':
        for item in items:
            item['finalizados_qtd'] = item['quantidade_total']
            for field in STAGES:
                item[field] = item['quantidade_total']
            item['status_item'] = 'Concluído'
    elif action == 'coletar':
        quantity = positive_int(payload.get('quantidade'), 'Quantidade coletada')
        if collected + quantity > total:
            raise ValueError('Coleta excede o saldo do cenário')
        if collected + quantity > sum(i['finalizados_qtd'] for i in items):
            raise ValueError('Finalize as unidades antes de coletá-las')
        state['coletas'].append({'id': str(uuid4()), 'quantidade': quantity,
                                 'created_at': datetime.now(timezone.utc).isoformat()})
    else:
        raise ValueError('Ação de simulação desconhecida')
    collected = sum(c['quantidade'] for c in state['coletas'])
    if collected == total:
        state['status'] = 'COLETADO'
    elif collected:
        state['status'] = 'COLETA_PARCIAL'
    elif all(i['finalizados_qtd'] == i['quantidade_total'] for i in items):
        state['status'] = 'CONCLUIDO'
    elif any(i['status_item'] != 'Pendente' for i in items):
        state['status'] = 'EM_PRODUCAO'
    else:
        state['status'] = 'AGUARDANDO'
    return state
