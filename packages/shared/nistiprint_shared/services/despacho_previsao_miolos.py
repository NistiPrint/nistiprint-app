"""Read-only forecast of miolos needed by dispatch lotes not yet published.

A lote on the Torre de Despacho is still just pending orders: nothing reaches
the production planning until the demand is published and `despachado_em` is
stamped. This module totals the miolos those lotes will ask for, by miolo and by
lote, so production can see the load before the lote is published.

It never reserves stock and never reads the database. Inputs are the lotes
already consolidated by `despacho_consolidar_pedidos` and the miolo products
with their stock balances, in the same shape `build_production_demand_plan`
takes. The per-unit miolo factor comes from the same BOM walk the planning uses,
so a forecast line and the published item agree on the quantity.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from nistiprint_shared.services.production_demand_planning import components_for_product


def _number(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _as_float(value):
    return float(value)


def _miolo_key(line):
    """Stable identity of a miolo: product id first, then the consolidation key."""
    if line.get('id_produto_miolo') is not None:
        return f"id:{line['id_produto_miolo']}"
    chave = line.get('miolo_chave') or line.get('miolo_nome')
    return f'chave:{chave}' if chave else None


def _unit_factor(line, nodes):
    """Miolos per unit of the line's product; 1 when the BOM does not say."""
    miolo_id = line.get('id_produto_miolo')
    produto_id = line.get('produto_id')
    if miolo_id is None or produto_id is None:
        return Decimal(1)
    components = components_for_product(produto_id, {str(miolo_id)}, nodes)
    return components.get(str(miolo_id)) or Decimal(1)


def build_previsao_miolos(lotes, products, graph=None):
    """Totals miolos per lote and per miolo.

    lotes: [{..., 'linhas': [consolidated line, ...]}]. Each line carries
        `quantidade`, `produto_id`, `descricao`, `id_produto_miolo`,
        `miolo_nome` and `miolo_chave`.
    products: miolo products as `{'id', 'name', 'sku', 'stock_details'}`.
    graph: effective BOM graph, used to apply the per-unit miolo factor.
    """
    nodes = (graph or {}).get('nodes') or {}
    product_map = {str(p['id']): p for p in products}
    miolos = {}
    lotes_out = []
    pedidos = 0
    linhas_sem_miolo = 0

    for lote in lotes:
        por_miolo = defaultdict(Decimal)
        nomes = {}
        sem_miolo = []
        for line in lote.get('linhas') or []:
            quantidade = _number(line.get('quantidade'))
            if quantidade <= 0:
                continue
            key = _miolo_key(line)
            motivo = 'Linha sem miolo identificado'
            if key:
                try:
                    # O fator sai antes de tocar em por_miolo: um defaultdict cria
                    # a chave ao ler, e uma ficha inválida deixaria um miolo órfão.
                    fator = _unit_factor(line, nodes)
                except ValueError as error:
                    motivo = str(error)
                else:
                    por_miolo[key] += quantidade * fator
                    nomes.setdefault(key, line)
                    continue
            linhas_sem_miolo += 1
            sem_miolo.append({
                'produto_id': line.get('produto_id'),
                'descricao': line.get('descricao') or line.get('sku_externo') or 'Item sem descrição',
                'quantidade': _as_float(quantidade),
                'motivo': motivo,
            })

        lote_miolos = []
        for key, quantidade in sorted(por_miolo.items(), key=lambda pair: -pair[1]):
            line = nomes[key]
            entry = {
                'miolo_key': key,
                'id_produto_miolo': line.get('id_produto_miolo'),
                'miolo_nome': line.get('miolo_nome') or line.get('miolo_chave'),
                'quantidade': _as_float(quantidade),
            }
            lote_miolos.append(entry)
            total = miolos.setdefault(key, {
                'miolo_key': key,
                'id_produto_miolo': line.get('id_produto_miolo'),
                'nome': line.get('miolo_nome') or line.get('miolo_chave'),
                'quantidade_total': Decimal(0),
                'por_lote': [],
            })
            total['quantidade_total'] += quantidade
            total['por_lote'].append({
                'lote_chave': lote.get('lote_chave'),
                'integration_id': lote.get('integration_id'),
                'nome_marketplace': lote.get('nome_marketplace'),
                'nome_modalidade': lote.get('nome_modalidade'),
                'data_limite_dia': lote.get('data_limite_dia'),
                'bucket': lote.get('bucket'),
                'quantidade': _as_float(quantidade),
            })

        pedidos += lote.get('qtd_pedidos') or 0
        lotes_out.append({
            **{key: value for key, value in lote.items() if key != 'linhas'},
            'total_miolos': _as_float(sum((_number(m['quantidade']) for m in lote_miolos), Decimal(0))),
            'miolos': lote_miolos,
            'sem_miolo': sem_miolo,
        })

    miolos_out = []
    for total in miolos.values():
        product = product_map.get(str(total['id_produto_miolo'])) if total['id_produto_miolo'] is not None else None
        quantidade = total['quantidade_total']
        if product:
            stock = product.get('stock_details') or {}
            disponivel = max(Decimal(0), _number(stock.get('quantidade_disponivel')))
            falta = max(Decimal(0), quantidade - disponivel)
            nome, sku = product.get('name') or product.get('nome') or total['nome'], product.get('sku')
        else:
            # Miolo sem cadastro de estoque: o estoque é desconhecido, não zero.
            disponivel, falta, nome, sku = None, quantidade, total['nome'], None
        miolos_out.append({
            'miolo_key': total['miolo_key'],
            'id_produto_miolo': total['id_produto_miolo'],
            'nome': nome,
            'sku': sku,
            'quantidade_total': _as_float(quantidade),
            'estoque_disponivel': None if disponivel is None else _as_float(disponivel),
            'sem_estoque_cadastrado': product is None,
            'falta': _as_float(falta),
            'por_lote': total['por_lote'],
        })
    miolos_out.sort(key=lambda row: (-row['falta'], -row['quantidade_total'], row['nome'] or ''))

    return {
        'lotes': lotes_out,
        'miolos': miolos_out,
        'resumo': {
            'total_pedidos': pedidos,
            'total_lotes': len(lotes_out),
            'total_miolos': _as_float(sum((_number(m['quantidade_total']) for m in miolos_out), Decimal(0))),
            'total_falta': _as_float(sum((_number(m['falta']) for m in miolos_out), Decimal(0))),
            'miolos_distintos': len(miolos_out),
            'linhas_sem_miolo': linhas_sem_miolo,
        },
    }
