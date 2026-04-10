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
from nistiprint_shared.utils import process_string
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("ImpressaoAPI")

impressao_api_bp = Blueprint('impressao_api', __name__, url_prefix='/api/v2/pedidos/impressao')


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

        for order_id in order_ids:
            order = _build_order_print_data(order_id, plataforma)
            if order:
                orders_data.append(order)

        return ApiResponse.success({
            'orders': orders_data,
            'total': len(orders_data)
        })

    except Exception as e:
        logger.error(f"Erro ao buscar dados de impressão: {e}", exc_info=True)
        return ApiResponse.error(str(e), 500)


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

        # 2. Buscar vínculos de integração
        vinculos_result = supabase_db.table('vinculos_integracao_pedido').select('*').eq('pedido_id', pedido_id).execute()
        vinculos = vinculos_result.data or []

        # Filtrar por plataforma se especificado
        if plataforma_filter:
            vinculos = [v for v in vinculos if v.get('plataforma', '').upper() == plataforma_filter.upper()]
            if not vinculos:
                return None

        # 3. Buscar itens do pedido
        itens_result = supabase_db.table('itens_pedido').select('*').eq('pedido_id', pedido_id).execute()
        itens_raw = itens_result.data or []

        # 4. Buscar personalizações
        personalizations_result = supabase_db.table('personalizacoes_pedido').select('*').eq('shopee_order_sn', pedido.get('codigo_pedido_externo')).execute()
        personalizations_raw = personalizations_result.data or []

        # 5. Montar estrutura de itens formatada
        itens_formatted = []
        for item in itens_raw:
            # Buscar personalizações associadas a este item
            item_pers = []
            for p in personalizations_raw:
                # Match por item_pedido_id (prioridade) ou descricao (fallback)
                if (p.get('item_pedido_id') == item.get('id')) or \
                   (p.get('item_pedido_id') is None and p.get('item_description') == item.get('descricao')):
                    item_pers.append({
                        'customization_name': p.get('customization_name'),
                        'customization_initial': p.get('customization_initial'),
                        'quantity_to_personalize': (p.get('metadata') or {}).get('quantity_to_personalize', 1),
                        'status': p.get('status'),
                    })

            # Calcular custom_tag
            custom_tag = ''
            if item.get('personalizado'):
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

        # 7. Determinar plataforma e numeroLoja
        plataforma_nome = ''
        numero_loja = ''
        for v in vinculos:
            plat = v.get('plataforma', '').upper()
            if plat == 'SHOPEE':
                numero_loja = pedido.get('codigo_pedido_externo', '')
                plataforma_nome = 'Shopee'
                break
            elif plat == 'BLING':
                plataforma_nome = 'Bling'

        # Se não encontrou Shopee, usar o external_id como fallback
        if not numero_loja:
            numero_loja = pedido.get('codigo_pedido_externo', '')

        # 8. Calcular total
        total_produtos = sum(i.get('valor', 0) * i.get('quantidade', 0) for i in itens_formatted)
        total_items = sum(i.get('quantidade', 0) for i in itens_formatted)
        has_custom_item = 1 if any(i.get('personalizado') or i.get('custom_tag') for i in itens_formatted) else 0

        # 9. Flag Flex
        is_flex = pedido.get('is_flex', False)
        servico_logistico = pedido.get('servico_logistico', '')

        return {
            'id': pedido.get('id'),
            'numero': pedido.get('numero_pedido', ''),
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
