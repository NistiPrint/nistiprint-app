"""
Endpoints para geração do template de impressão (papéis de pedido).

Fluxo:
1. Frontend chama GET /api/v2/pedidos/impressao?order_ids=1,2,3
2. Backend monta dados completos de cada pedido (cliente, itens, personalizações, custom_tags)
3. Frontend renderiza componente React com CSS @media print e dispara window.print()
"""

from flask import Blueprint, request
from routes.auth import login_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_erp_reference_service import order_erp_reference_service
from nistiprint_shared.utils import process_string
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("ImpressaoAPI")

impressao_api_bp = Blueprint('impressao_api', __name__, url_prefix='/api/v2/pedidos/impressao')

# Nome de exibicao por marketplace. O template usa este valor para o cabecalho
# do pedido e para escolher o icone.
MARKETPLACE_DISPLAY_NAMES = {
    'shopee': 'Shopee',
    'mercadolivre': 'Mercado Livre',
    'amazonfba_classic': 'Amazon',
    'amazon_fulfillment': 'Amazon',
    'shein': 'Shein',
    'tiktokshop': 'TikTok Shop',
    'kwai': 'Kwai',
    'lojaintegrada': 'Loja Integrada',
    'magazineluiza': 'Magazine Luiza',
}


@impressao_api_bp.route('', methods=['GET'])
@login_required
def get_impressao_data():
    """
    Retorna dados formatados para o template de impressão.

    Query params:
    - order_ids: str (lista de IDs separados por vírgula)
    - plataforma: str (filtrar por plataforma: BLING, SHOPEE)

    Retorna:
    - orders: lista de pedidos formatados para impressão
    """
    try:
        order_ids_param = request.args.get('order_ids')
        plataforma = request.args.get('plataforma')

        if not order_ids_param:
            return ApiResponse.error('order_ids é obrigatório', 400)

        order_ids = [int(id.strip()) for id in order_ids_param.split(',') if id.strip()]

        orders_data = []
        blocked_orders = []

        resolution = order_erp_reference_service.resolve_many(order_ids, allow_remote=True)
        ready_ids = {item['pedido_id'] for item in resolution['ready']}
        blocked_orders.extend(resolution['blocked'])
        for order_id in order_ids:
            if order_id not in ready_ids:
                continue
            order = _build_order_print_data(order_id, plataforma)
            if order:
                orders_data.append(order)
            else:
                blocked_orders.append({
                    'pedido_id': order_id,
                    'status': 'invalid_print_data',
                    'message': 'Pedido sem número Bling ou dados para impressão',
                })

        orders_data.sort(key=_print_sort_key)

        return ApiResponse.success({
            'orders': orders_data,
            'total': len(orders_data),
            'blocked_orders': blocked_orders,
            'blocked_total': len(blocked_orders)
        })

    except Exception as e:
        logger.error(f"Erro ao buscar dados de impressão: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


def _primeira_custom_tag(order: dict) -> str:
    """Primeira tag de personalizacao do pedido, em ordem de item."""
    for item in order.get('itens') or []:
        tag = (item.get('custom_tag') or '').strip()
        if tag:
            return tag
    return ''


def _print_sort_key(order: dict):
    """Ordem de impressao — mesma chave do legado.

    Do legado (`kb/legado/services/bling/bling.py`):

        1. itens personalizados: nao depois sim (agrupa pedidos com item
           personalizado)
        2. quais itens personalizados: ordem alfabetica (agrupa os
           personalizados por modelo)
        3. quantidade total de itens: ordem crescente
        4. quantos itens diferentes: ordem crescente

    A versao anterior mantinha so o primeiro criterio e usava `numeroLoja` como
    desempate. `numeroLoja` e efetivamente aleatorio em relacao ao produto, o
    que desfazia justamente o agrupamento por modelo — que e o ganho
    operacional da ordenacao: quem imprime quer as mesmas capas juntas.
    """
    itens = order.get('itens') or []
    return (
        1 if order.get('hasCustomItem') else 0,
        order.get('total_items') or 0,
        len(itens),
        len([i for i in itens if (i.get('custom_tag') or '').strip()]),
        _primeira_custom_tag(order),
    )


def _build_order_print_data(pedido_id: int, plataforma_filter: str = None) -> dict | None:
    """
    Monta dados completos de um pedido para o template de impressão.
    Inclui: cliente, itens, personalizações, custom_tags.
    """
    try:
        # 1. Buscar pedido core
        pedido_result = supabase_db.table('pedidos').select('*').eq('id', pedido_id).single().execute()
        if not pedido_result.data:
            return None

        pedido = pedido_result.data
        erp_number = pedido.get('erp_order_number')
        if not erp_number:
            return None

        # 2. Plataforma de origem.
        #
        # Antes isto vinha de `vinculos_integracao_pedido`, tabela que esta
        # vazia em producao. O efeito era duplo: `plataforma` chegava sempre em
        # branco no template (que a usa para o icone e o cabecalho do pedido) e,
        # pior, informar `plataforma_filter` fazia *todo* pedido ser descartado,
        # porque a lista de vinculos nunca tinha nada para casar.
        #
        # A origem canonica ja esta no proprio pedido.
        plataforma_slug = (pedido.get('marketplace_module_id') or '').strip().lower()
        if plataforma_filter:
            filtro = plataforma_filter.strip().lower()
            # `BLING` nao e marketplace: e o caminho de ingest. Um pedido
            # ingerido via ERP satisfaz o filtro qualquer que seja seu canal.
            if filtro == 'bling':
                if (pedido.get('ingest_source') or '').lower() != 'bling':
                    return None
            elif plataforma_slug != filtro:
                return None

        # 3. Buscar itens do pedido com tag_impressao_pdf do produto
        itens_result = supabase_db.table('itens_pedido').select('*, produtos(tag_impressao_pdf)').eq('pedido_id', pedido_id).execute()
        itens_raw = itens_result.data or []

        # 4. Buscar personalizações
        personalizations_result = supabase_db.table('personalizacoes_pedido').select('*').eq('shopee_order_sn', pedido.get('codigo_pedido_externo')).execute()
        personalizations_raw = personalizations_result.data or []

        # 5. Montar estrutura de itens formatada
        itens_formatted = []
        for item in itens_raw:
            # Extrair tag do produto relacionado, se existir
            tag_do_produto = None
            if item.get('produtos'):
                tag_do_produto = item.get('produtos').get('tag_impressao_pdf')
            
            # Buscar personalizações associadas a este item
            item_pers = []
            for p in personalizations_raw:
                # Match por item_pedido_id (prioridade) ou descricao (fallback)
                if (p.get('item_pedido_id') == item.get('id')) or \
                   (p.get('item_pedido_id') is None and p.get('item_description') == item.get('descricao')):
                    detalhes = p.get('detalhes_personalizacao') or {}
                    metadata = p.get('metadata') or {}
                    item_pers.append({
                        'customization_name': p.get('customization_name'),
                        'customization_initial': p.get('customization_initial'),
                        'quantity_to_personalize': detalhes.get('quantity_to_personalize')
                            or metadata.get('quantity_to_personalize', 1),
                        'status': p.get('status'),
                    })

            # Calcular custom_tag
            custom_tag = tag_do_produto or ''
            if not custom_tag and item.get('personalizado'):
                custom_tag = process_string({
                    'codigo': item.get('sku_externo', ''),
                    'descricao': item.get('descricao', '')
                })

            item_formatted = {
                'descricao': item.get('descricao', ''),
                'codigo': item.get('sku_externo', ''),
                'quantidade': item.get('quantidade', 0),
                'valor': item.get('preco_unitario', 0),
                'variacao': None,  # TODO: adicionar coluna se necessário
                'personalizado': item.get('personalizado', False),
                'personalizations': item_pers,
                'custom_tag': custom_tag,
            }
            itens_formatted.append(item_formatted)

        # 6. Montar dados do contato
        contato = pedido.get('informacoes_cliente', {}) or {}
        if isinstance(contato, str):
            import json
            try:
                contato = json.loads(contato)
            except:
                contato = {}

        # 7. Nome de exibição da plataforma e numeroLoja
        plataforma_nome = MARKETPLACE_DISPLAY_NAMES.get(
            plataforma_slug, plataforma_slug.replace('_', ' ').title()
        ) if plataforma_slug else ''
        numero_loja = pedido.get('marketplace_order_id') or pedido.get('codigo_pedido_externo', '')

        # 8. Calcular total
        total_produtos = sum(i.get('valor', 0) * i.get('quantidade', 0) for i in itens_formatted)
        total_items = sum(i.get('quantidade', 0) for i in itens_formatted)
        has_custom_item = 1 if any(i.get('personalizado') or i.get('custom_tag') for i in itens_formatted) else 0

        # 9. Flag Flex
        is_flex = pedido.get('is_flex', False)
        servico_logistico = pedido.get('servico_logistico', '')

        return {
            'id': pedido.get('id'),
            'numero': str(erp_number),
            'numeroLoja': numero_loja,
            'contato': {
                'nome': pedido.get('cliente_nome', contato.get('nome', '')),
                'numeroDocumento': contato.get('numeroDocumento', pedido.get('cliente_documento', '')),
                'endereco': contato.get('endereco', ''),
                'telefone': contato.get('telefone', pedido.get('cliente_telefone', '')),
                'email': contato.get('email', pedido.get('cliente_email', '')),
            },
            'itens': itens_formatted,
            'totalProdutos': total_produtos,
            'total_items': total_items,
            'hasCustomItem': has_custom_item,
            'plataforma': plataforma_nome,
            'is_flex': is_flex,
            'servico_logistico': servico_logistico,
            'data_pedido': pedido.get('data_venda'),
        }

    except Exception as e:
        logger.error(f"Erro ao montar dados de impressão para pedido {pedido_id}: {e}", exc_info=True)
        return None
