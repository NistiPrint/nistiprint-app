from flask import Blueprint, request, jsonify
from routes.auth import login_required
from services.order_service import order_service
from models.situacao_pedido import SituacaoPedido
from services.database.v2.supabase_db_service import supabase_db
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