from flask import Blueprint, render_template, jsonify, request
from routes.auth import login_required
from services.orders_query_service import orders_query_service
from utils.api_response import ApiResponse

vendas_bp = Blueprint('vendas', __name__, url_prefix='/vendas')
vendas_api_bp = Blueprint('vendas_api', __name__, url_prefix='/api/v2/vendas')

# API Vendas routes
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

