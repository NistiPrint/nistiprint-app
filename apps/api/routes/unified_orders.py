from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.models.situacao_pedido import SituacaoPedido
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse

unified_orders_bp = Blueprint('unified_orders', __name__, url_prefix='/api/v2/order')

@unified_orders_bp.route('/list', methods=['POST'])
@login_required
def get_unified_orders():
    """Obtém lista de pedidos unificados com filtros e paginação"""
    try:
        data = request.get_json(silent=True) or {}

        page = int(data.get('page', 1))
        per_page = int(data.get('perPage', 50))

        # O list_orders já trata os filtros e a query
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
    """
    Obtém lista de pedidos unificados com filtros avançados para consolidação.
    
    Query params:
    - status_id: Filtrar por status do pedido
    - canal_venda_id: Filtrar por canal de venda
    - has_demanda: true/false (pedidos com/sem demanda)
    - delivery_start: Data início do período de entrega
    - delivery_end: Data fim do período de entrega
    - search: Termo de busca (cliente, numero_pedido, codigo_externo)
    - page: Página (default: 1)
    - limit: Limite por página (default: 50)
    """
    try:
        # Parâmetros de filtro
        status_id = request.args.get('status_id', type=int)
        canal_venda_id = request.args.get('canal_venda_id', type=int)
        has_demanda = request.args.get('has_demanda')
        delivery_start = request.args.get('delivery_start')
        delivery_end = request.args.get('delivery_end')
        search = request.args.get('search')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        
        # Converter has_demanda para booleano
        if has_demanda == 'true':
            has_demanda = True
        elif has_demanda == 'false':
            has_demanda = False
        else:
            has_demanda = None
        
        # Calcular offset
        offset = (page - 1) * limit
        
        # Chamar função RPC
        result = supabase_db.rpc('get_pedidos_com_filtros_avancados', {
            'p_situacao_pedido_id': status_id,
            'p_canal_venda_id': canal_venda_id,
            'p_has_demanda': has_demanda,
            'p_delivery_start_date': delivery_start,
            'p_delivery_end_date': delivery_end,
            'p_search_term': search,
            'p_limit': limit,
            'p_offset': offset
        }).execute()
        
        pedidos = result.data or []
        
        # Contar total (sem limit/offset)
        count_result = supabase_db.rpc('get_pedidos_com_filtros_avancados', {
            'p_situacao_pedido_id': status_id,
            'p_canal_venda_id': canal_venda_id,
            'p_has_demanda': has_demanda,
            'p_delivery_start_date': delivery_start,
            'p_delivery_end_date': delivery_end,
            'p_search_term': search,
            'p_limit': 10000,
            'p_offset': 0
        }).execute()
        
        total = len(count_result.data) if count_result.data else 0
        
        return ApiResponse.success(data={
            'orders': pedidos,
            'total': total,
            'page': page,
            'per_page': limit
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@unified_orders_bp.route('/status-options', methods=['GET'])
@login_required
def get_status_options():
    """Obtém opções de status disponíveis para pedidos"""
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
            return ApiResponse.error(message="ID do pedido e novo status são obrigatórios", status_code=400)
        
        # Verificar se o novo status existe
        status_response = supabase_db.client.table('situacoes_pedido').select('id').eq('nome', new_status).execute()
        if not status_response.data:
            return ApiResponse.error(message=f"Status '{new_status}' não encontrado", status_code=404)
        
        new_status_id = status_response.data[0]['id']
        
        # Atualizar o status do pedido
        update_response = supabase_db.client.table('pedidos').update({
            'situacao_pedido_id': new_status_id
        }).eq('id', order_id).execute()
        
        if not update_response.data:
            return ApiResponse.error(message="Pedido não encontrado", status_code=404)
        
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
    """Obtém detalhes de um pedido específico"""
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
            return ApiResponse.error(message="Pedido não encontrado", status_code=404)
        
        order = order_response.data[0]
        
        return ApiResponse.success(data={'order': order})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)





