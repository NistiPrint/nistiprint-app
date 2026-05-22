from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.models.situacao_pedido import SituacaoPedido
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
from utils.order_filters_adapter import (
    build_origin_options,
    normalize_date_end,
    normalize_date_start,
    parse_bool_strict,
    parse_int_safe,
    resolve_order_ids_from_origin,
    sanitize_search_term,
)

unified_orders_bp = Blueprint('unified_orders', __name__, url_prefix='/api/v2/order')

@unified_orders_bp.route('/list', methods=['POST'])
@login_required
def get_unified_orders():
    """ObtÃ©m lista de pedidos unificados com filtros e paginaÃ§Ã£o"""
    try:
        data = request.get_json(silent=True) or {}

        page = int(data.get('page', 1))
        per_page = int(data.get('perPage', 50))

        # O list_orders jÃ¡ trata os filtros e a query
        result = order_service.list_orders(
            page=page,
            per_page=per_page,
            filters=data
        )

        return ApiResponse.success(data=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


@unified_orders_bp.route('/list-advanced', methods=['GET'])
@login_required
def get_unified_orders_advanced():
    """Obtém lista de pedidos com filtros avançados via RPC otimizada."""
    try:
        # 1. Extração e sanitização de parâmetros
        params = {
            'p_situacao_pedido_id': parse_int_safe(request.args.get('status_id')),
            'p_bling_integration_id': parse_int_safe(request.args.get('bling_integration_id')),
            'p_canal_venda_id': parse_int_safe(request.args.get('canal_venda_id')),
            'p_origem_pedido_key': request.args.get('origem_pedido_key') or None,
            'p_has_demanda': parse_bool_strict(request.args.get('has_demanda')),
            'p_is_flex': parse_bool_strict(request.args.get('is_flex')),
            'p_is_fulfillment': parse_bool_strict(request.args.get('is_fulfillment')),
            'p_is_personalizado': parse_bool_strict(request.args.get('is_personalizado')),
            'p_delivery_start_date': normalize_date_start(request.args.get('delivery_start')),
            'p_delivery_end_date': normalize_date_end(request.args.get('delivery_end')),
            'p_pedido_date_start': request.args.get('pedido_date_start') or None,
            'p_pedido_date_end': request.args.get('pedido_date_end') or None,
            'p_search_term': sanitize_search_term(request.args.get('search')),
            'p_sort': request.args.get('sort', 'numero_pedido'),
            'p_order': request.args.get('order', 'desc'),
            'p_limit': parse_int_safe(request.args.get('limit')) or 50,
            'p_offset': ((parse_int_safe(request.args.get('page')) or 1) - 1) * (parse_int_safe(request.args.get('limit')) or 50)
        }

        # Validação de limites
        if params['p_limit'] < 1: params['p_limit'] = 50
        if params['p_limit'] > 200: params['p_limit'] = 200
        if params['p_offset'] < 0: params['p_offset'] = 0

        # 2. Chamada à RPC
        rpc_result = supabase_db.rpc('list_pedidos_filtrados', params).execute()
        
        pedidos = rpc_result.data or []
        total_count = pedidos[0].get('total_count', 0) if pedidos else 0

        # 3. Formatação da resposta para compatibilidade com o frontend
        formatted_orders = []
        for p in pedidos:
            # Garantir estrutura de status esperada pelo PedidosListPage.jsx
            p['status'] = {
                'id': p.get('situacao_pedido_id'),
                'nome': p.get('situacao_nome', 'Desconhecido'),
                'cor': p.get('situacao_cor', '#9ca3af')
            }
            # Campo enviar_ate_formatado esperado pelo frontend
            p['enviar_ate_formatado'] = p.get('data_limite_envio') or 'N/A'
            
            # Limpeza de campos internos da RPC antes de enviar ao frontend
            # Mantemos tem_demanda, demanda_id, etc.
            formatted_orders.append(p)

        page = parse_int_safe(request.args.get('page')) or 1
        limit = params['p_limit']

        return ApiResponse.success(data={
            'orders': formatted_orders,
            'pedidos': formatted_orders,
            'total': total_count,
            'pagination': {
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': (total_count + limit - 1) // limit if limit > 0 else 0
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)
@unified_orders_bp.route('/status-options', methods=['GET'])
@login_required
def get_status_options():
    """ObtÃ©m opÃ§Ãµes de status disponÃ­veis para pedidos"""
    try:
        response = supabase_db.client.table('situacoes_pedido').select('*').execute()
        status_options = response.data
        
        return ApiResponse.success(data={'status_options': status_options})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@unified_orders_bp.route('/update-status', methods=['POST'])
@login_required
def update_order_status():
    """Atualiza o status de um pedido"""
    try:
        data = request.get_json(silent=True) or {}
        
        order_id = data.get('order_id')
        new_status = data.get('new_status')
        
        if not order_id or not new_status:
            return ApiResponse.error(message="ID do pedido e novo status sÃ£o obrigatÃ³rios", status_code=400)
        
        # Verificar se o novo status existe
        status_response = supabase_db.client.table('situacoes_pedido').select('id').eq('nome', new_status).execute()
        if not status_response.data:
            return ApiResponse.error(message=f"Status '{new_status}' nÃ£o encontrado", status_code=404)
        
        new_status_id = status_response.data[0]['id']
        
        # Atualizar o status do pedido
        update_response = supabase_db.client.table('pedidos').update({
            'situacao_pedido_id': new_status_id
        }).eq('id', order_id).execute()
        
        if not update_response.data:
            return ApiResponse.error(message="Pedido nÃ£o encontrado", status_code=404)
        
        # Retornar o pedido atualizado
        updated_order = supabase_db.client.table('pedidos').select(
            '*, situacao_pedido:situacoes_pedido(nome, descricao, cor_status)'
        ).eq('id', order_id).execute().data[0]
        
        return ApiResponse.success(data={'order': updated_order})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@unified_orders_bp.route('/details/<int:order_id>', methods=['GET'])
@login_required
def get_order_details(order_id):
    """ObtÃ©m detalhes de um pedido especÃ­fico"""
    try:
        # Obter pedido com seus itens
        order_response = supabase_db.client.table('pedidos').select(
            '''
            *,
            situacao_pedido:situacoes_pedido(nome, descricao, cor_status),
            itens_pedido!inner(*, produto:produtos(nome, sku))
            '''
        ).eq('id', order_id).execute()
        
        if not order_response.data:
            return ApiResponse.error(message="Pedido nÃ£o encontrado", status_code=404)
        
        order = order_response.data[0]
        
        return ApiResponse.success(data={'order': order})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


