from flask import Blueprint, render_template, jsonify, request
from routes.auth import login_required
from nistiprint_shared.services.orders_query_service import orders_query_service
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from utils.api_response import ApiResponse

vendas_bp = Blueprint('vendas', __name__, url_prefix='/vendas')
vendas_api_bp = Blueprint('vendas_api', __name__, url_prefix='/api/v2/vendas')

@vendas_api_bp.route('/unified-orders', methods=['GET'])
@login_required
def api_unified_orders():
    """
    Retorna a lista de pedidos unificados com paginação e filtros.
    """
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('perPage', 50))
        
        filters = {
            'searchTerm': request.args.get('searchTerm'),
            'status': request.args.get('status'),
            'origin': request.args.get('origin'),
            'canal_venda_id': request.args.get('canal_venda_id'),
            'startDate': request.args.get('startDate'),
            'endDate': request.args.get('endDate'),
        }
        
        # Remove filtros vazios
        filters = {k: v for k, v in filters.items() if v}

        result = order_service.list_orders(page=page, per_page=per_page, filters=filters)
        return ApiResponse.success(data=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@vendas_api_bp.route('/order-status-options', methods=['GET'])
@login_required
def api_order_status_options():
    """
    Retorna as opções de status de pedidos unificados.
    """
    try:
        options = order_service.get_order_status_options()
        return ApiResponse.success(data={'status_options': options})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@vendas_api_bp.route('/canal-venda-options', methods=['GET'])
@login_required
def api_canal_venda_options():
    """
    Retorna as opções de canais de venda.
    """
    try:
        options = canal_venda_service.get_all()
        return ApiResponse.success(data={'canal_venda_options': options})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

@vendas_api_bp.route('/personalizadas', methods=['GET'])
@login_required
def api_personalizadas():
    try:
        mode = request.args.get('mode')
        orders = orders_query_service.get_personalized_orders(mode=mode)
        # Wrap in a dict with 'bling_orders' key to maintain backward compatibility 
        # with the frontend if it expects { bling_orders: [...] } inside the data, 
        # OR use ApiResponse standard.
        # Looking at the old code: return jsonify({'bling_orders': processed_orders})
        
        return ApiResponse.success(data={'bling_orders': orders})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)

# Regular Vendas routes
@vendas_bp.route('/personalizadas_legacy')
@login_required
def personalizadas():
    try:
        orders = orders_query_service.get_personalized_orders()
        return render_template('vendas/personalizadas.html', bling_orders=orders)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('error.html', error=str(e)), 500






