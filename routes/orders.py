from flask import Blueprint, request, jsonify
from routes.auth import login_required
from services.platform_api_service import platform_api_service
from utils.api_response import ApiResponse

orders_api_bp = Blueprint('orders_api', __name__, url_prefix='/api/v2/order')

@orders_api_bp.route('/get_order_detail', methods=['POST'])
@login_required
def get_order_detail():
    """
    Endpoint to fetch order details directly from an integrated platform (Live Query).
    This is used for verification ('conferência') and does not persist data.
    
    Expects JSON: { 
        "order_sn_list": "SN1,SN2", 
        "module_id": "shopee" (default),
        "instance_id": "optional_id" 
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        # Priority to JSON, then query params
        order_sn_str = data.get('order_sn_list') or request.args.get('order_sn_list')
        instance_id = data.get('instance_id') or request.args.get('instance_id')
        module_id = data.get('module_id') or request.args.get('module_id') or "shopee"
        
        if not order_sn_str:
            return ApiResponse.error(message="Parâmetro order_sn_list é obrigatório.", status_code=400)
            
        # Split by comma and clean whitespace
        order_sn_list = [sn.strip() for sn in order_sn_str.split(',') if sn.strip()]
        
        if not order_sn_list:
            return ApiResponse.error(message="Lista de IDs de pedidos inválida.", status_code=400)
            
        # Call the generic platform API service
        result = platform_api_service.get_order_detail(
            order_sn_list=order_sn_list, 
            instance_id=instance_id,
            module_id=module_id
        )
        
        # Log result for debugging
        # print(f"DEBUG: Platform API Result: {result}")
        
        # Shopee returns "error": "" on success, so we must check if it has content
        if result.get("error") and result.get("error") != "":
            return ApiResponse.error(message=result["error"], errors=result, status_code=500)
            
        # Also check for Shopee-specific error messages in the root
        if result.get("message") and not result.get("response") and result.get("error") != "":
             return ApiResponse.error(message=result["message"], errors=result, status_code=500)

        # Return the raw platform data directly
        return ApiResponse.success(data=result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)