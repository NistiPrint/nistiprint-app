from flask import Blueprint, request, jsonify
from routes.auth import login_required
from nistiprint_shared.services.order_reprocess_service import order_reprocess_service
from nistiprint_shared.services.order_sync_service import order_sync_service
from utils.api_response import ApiResponse

order_reprocess_bp = Blueprint('order_reprocess', __name__, url_prefix='/api/admin/orders')

@order_reprocess_bp.route('/reprocess', methods=['POST'])
@login_required
def reprocess_order():
    """
    Endpoint para reprocessar um pedido específico.
    Busca dados atualizados de todas as integrações.
    
    Expects JSON: {
        "pedido_id": int,
        "integration_id": int (opcional)
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        pedido_id = data.get('pedido_id')
        integration_id = data.get('integration_id')
        
        if not pedido_id:
            return ApiResponse.error(message="Parâmetro pedido_id é obrigatório.", status_code=400)
        
        result = order_reprocess_service.reprocess_order(pedido_id, integration_id)
        
        if result.get('success'):
            return ApiResponse.success(data=result, message="Pedido reprocessado com sucesso")
        else:
            return ApiResponse.error(message=result.get('error', 'Erro ao reprocessar pedido'), status_code=500)
            
    except Exception as e:
        return ApiResponse.error(message=f"Erro ao processar requisição: {str(e)}", status_code=500)

@order_reprocess_bp.route('/reprocess-batch', methods=['POST'])
@login_required
def reprocess_batch():
    """
    Endpoint para reprocessar um lote de pedidos.
    
    Expects JSON: {
        "pedido_ids": [int, int, ...],
        "integration_id": int (opcional)
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        pedido_ids = data.get('pedido_ids')
        integration_id = data.get('integration_id')
        
        if not pedido_ids or not isinstance(pedido_ids, list):
            return ApiResponse.error(message="Parâmetro pedido_ids é obrigatório e deve ser uma lista.", status_code=400)
        
        result = order_reprocess_service.reprocess_batch(pedido_ids, integration_id)
        
        if result.get('success'):
            return ApiResponse.success(data=result, message="Lote de pedidos reprocessado com sucesso")
        else:
            return ApiResponse.error(message=result.get('error', 'Erro ao reprocessar lote'), status_code=500)
            
    except Exception as e:
        return ApiResponse.error(message=f"Erro ao processar requisição: {str(e)}", status_code=500)

@order_reprocess_bp.route('/reprocess-by-canal', methods=['POST'])
@login_required
def reprocess_by_canal():
    """
    Endpoint para reprocessar pedidos de um canal de venda específico.

    Expects JSON: {
        "canal_venda_id": int,
        "date_range": {
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD"
        } (opcional),
        "integration_id": int (opcional)
    }
    """
    try:
        data = request.get_json(silent=True) or {}

        canal_venda_id = data.get('canal_venda_id')
        date_range = data.get('date_range')
        integration_id = data.get('integration_id')

        if not canal_venda_id:
            return ApiResponse.error(message="Parâmetro canal_venda_id é obrigatório.", status_code=400)

        result = order_reprocess_service.reprocess_by_canal(canal_venda_id, date_range, integration_id)

        if result.get('success'):
            return ApiResponse.success(data=result, message="Pedidos do canal reprocessados com sucesso")
        else:
            return ApiResponse.error(message=result.get('error', 'Erro ao reprocessar pedidos do canal'), status_code=500)

    except Exception as e:
        return ApiResponse.error(message=f"Erro ao processar requisição: {str(e)}", status_code=500)

@order_reprocess_bp.route('/sync-shopee', methods=['POST'])
@login_required
def sync_shopee_order():
    """
    Endpoint para forçar sync manual de pedido Shopee.
    Busca dados atualizados diretamente da API Shopee.

    Expects JSON: {
        "order_sn": str (Shopee order ID)
    }
    """
    try:
        data = request.get_json(silent=True) or {}

        order_sn = data.get('order_sn')

        if not order_sn:
            return ApiResponse.error(message="Parâmetro order_sn é obrigatório.", status_code=400)

        result = order_sync_service.sync_shopee_order(order_sn)

        if result.get('success') or not result.get('error'):
            return ApiResponse.success(data=result, message="Pedido Shopee sincronizado com sucesso")
        else:
            return ApiResponse.error(message=result.get('error', 'Erro ao sincronizar pedido Shopee'), status_code=500)

    except Exception as e:
        return ApiResponse.error(message=f"Erro ao processar requisição: {str(e)}", status_code=500)
