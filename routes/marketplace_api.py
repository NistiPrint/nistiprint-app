"""
API routes for integration marketplace functionality
"""
from flask import Blueprint, jsonify, request, redirect, url_for
from datetime import datetime, timedelta
from services.integration_module_service import integration_module_service
from services.installed_integration_service import installed_integration_service
from models.integration_module import InstalledIntegration
from services.platform_auth_service import platform_auth_service
from services.integration_module_service import integration_module_service
from utils.api_response import ApiResponse

marketplace_api_bp = Blueprint('marketplace_api', __name__, url_prefix='/api/v2/marketplace')


import os

@marketplace_api_bp.route('/auth/init/<module_id>', methods=['POST'])
def init_auth(module_id):
    """Initialize OAuth flow by generating the correct URL"""
    try:
        data = request.get_json()
        config = data.get('config', {})
        instance_id = data.get('instance_id') # If we have a pending instance
        custom_redirect_uri = data.get('redirect_uri') # Allow frontend to force a specific URI
        
        # Determine redirect URI (must match what is registered in the platform)
        if custom_redirect_uri:
             redirect_uri = custom_redirect_uri
        else:
            # Use PUBLIC_URL env var if set (essential for Cloud Run / Production), otherwise fallback to request.url_root
            public_url = os.environ.get('PUBLIC_URL')
            if public_url:
                # Remove trailing slash from public_url if present
                public_url = public_url.rstrip('/')
                redirect_uri = f"{public_url}{url_for('marketplace_api.auth_callback', platform=module_id)}"
            else:
                redirect_uri = url_for('marketplace_api.auth_callback', platform=module_id, _external=True)
        
        # Generate URL using service
        auth_url = platform_auth_service.generate_auth_url(
            module_id, 
            config, 
            redirect_uri,
            state=instance_id # Pass instance_id as state to retrieve it later
        )
        
        if not auth_url:
            return jsonify({'error': 'Could not generate auth URL for this platform'}), 400
            
        return jsonify({'auth_url': auth_url}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/auth/exchange/<platform>', methods=['POST'])
def auth_exchange_manual(platform):
    """Manual exchange of code for token (for local dev or manual flow)"""
    try:
        data = request.get_json()
        code = data.get('code')
        instance_id = data.get('instance_id')
        shop_id = data.get('shop_id')
        
        if not code or not instance_id:
            return jsonify({'error': 'Missing code or instance_id'}), 400

        # 1. Retrieve the pending installation
        installation = installed_integration_service.get_installed_by_id(instance_id)
        if not installation:
            return jsonify({'error': f"Installation {instance_id} not found"}), 404
            
        # 2. Exchange code for tokens
        try:
            tokens = platform_auth_service.exchange_code_for_token(
                platform, 
                installation.config, 
                code, 
                shop_id
            )
        except Exception as e:
            return jsonify({'error': f"Error exchanging token: {str(e)}"}), 500
            
        # 3. Update the installation with tokens
        update_data = {
            'credentials': {
                'access_token': tokens.get('access_token'),
                'refresh_token': tokens.get('refresh_token'),
                'expires_in': tokens.get('expires_in'),
                'shop_id': shop_id
            },
            'sync_status': 'active',
            'is_active': True
        }
        
        installed_integration_service.update_installed(instance_id, update_data)
        
        return jsonify({'success': True, 'message': 'Authentication successful'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/auth/callback/<platform>', methods=['GET'])
def auth_callback(platform):
    """Callback for OAuth2 authentication flows"""
    try:
        code = request.args.get('code')
        instance_id = request.args.get('state') # We passed instance_id as state
        shop_id = request.args.get('shop_id') # Specific to Shopee
        
        if not code:
            return "Error: No authorization code provided", 400

        if not instance_id:
             return "Error: No instance ID (state) provided", 400

        # 1. Retrieve the pending installation
        installation = installed_integration_service.get_installed_by_id(instance_id)
        if not installation:
            return f"Error: Installation {instance_id} not found", 404
            
        # 2. Exchange code for tokens
        try:
            tokens = platform_auth_service.exchange_code_for_token(
                platform, 
                installation.config, # Use the config we saved in Step 1
                code, 
                shop_id
            )
        except Exception as e:
            return f"Error exchanging token: {str(e)}", 500
            
        # 3. Update the installation with tokens
        update_data = {
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
            'expires_at': (datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 0))).isoformat() if tokens.get('expires_in') else None,
            'credentials': {
                'shop_id': shop_id,
                'raw_response': tokens.get('raw_response')
            },
            'sync_status': 'active', # Mark as active/ready
            'is_active': True
        }
        
        installed_integration_service.update_installed(instance_id, update_data)
        
        # 4. Redirect to frontend success page
        # Assuming frontend is served at / (or /configuracoes/integracoes)
        # We can append a query param to show a success toast
        frontend_url = url_for('integracoes.admin_integrations', _external=True) # or specific frontend route
        # Hack for React routing if served separately or via template:
        # Since we serve React at /, we probably want to go to /configuracoes/integracoes
        base_url = request.url_root.rstrip('/')
        return redirect(f"{base_url}/configuracoes/integracoes?status=success&platform={platform}")

    except Exception as e:
        return f"System Error: {str(e)}", 500


@marketplace_api_bp.route('/modules', methods=['GET'])
def get_available_modules():
    """Get all available integration modules in the marketplace"""
    try:
        # Get optional filters from query parameters
        category = request.args.get('category')
        tags_param = request.args.get('tags')  # Comma-separated tags
        tags = tags_param.split(',') if tags_param else None
        
        if category and tags:
            # This would require a more complex query, for now we'll filter in memory
            all_modules = integration_module_service.get_all_modules()
            filtered_modules = [
                module for module in all_modules
                if module.category.lower() == category.lower() and
                (not tags or any(tag.lower() in [t.lower() for t in module.tags] for tag in tags))
            ]
            modules = filtered_modules
        elif category:
            modules = integration_module_service.get_modules_by_category(category)
        elif tags:
            modules = integration_module_service.get_modules_by_tags(tags)
        else:
            modules = integration_module_service.get_all_modules()
        
        # Convert modules to dictionaries for JSON serialization
        modules_data = []
        for module in modules:
            module_dict = module.to_dict()
            module_dict['id'] = module.id
            modules_data.append(module_dict)
        
        return jsonify({'modules': modules_data}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/modules/<module_id>', methods=['GET'])
def get_module_details(module_id):
    """Get details of a specific integration module"""
    try:
        module = integration_module_service.get_module_by_id(module_id)
        if not module:
            return jsonify({'error': 'Module not found'}), 404
        
        module_data = module.to_dict()
        module_data['id'] = module.id
        
        return jsonify({'module': module_data}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/install', methods=['POST'])
def install_module():
    """Install a new instance of an integration module"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        # Extract required fields
        module_id = data.get('module_id')
        instance_name = data.get('instance_name')
        user_id = data.get('user_id')  # In a real app, this would come from authentication
        
        if not module_id or not instance_name or not user_id:
            return jsonify({'error': 'Missing required fields: module_id, instance_name, user_id'}), 400
        
        # Optional fields
        config = data.get('config', {})
        credentials = data.get('credentials', {})
        
        # Install the module
        instance_id = installed_integration_service.install_module(
            user_id=user_id,
            module_id=module_id,
            instance_name=instance_name,
            config=config,
            credentials=credentials
        )
        
        # Get the newly created installation
        installation = installed_integration_service.get_installed_by_id(instance_id)
        installation_data = installation.to_dict()
        installation_data['id'] = installation.id
        
        return jsonify({
            'success': True,
            'message': 'Module installed successfully',
            'instance_id': instance_id,
            'installation': installation_data
        }), 201
    
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed', methods=['GET'])
def get_installed_integrations():
    """Get all installed integration instances for a user"""
    try:
        # In a real app, user_id would come from authentication
        user_id = request.args.get('user_id')
        
        installations = installed_integration_service.get_all_installed(user_id=user_id)
        
        installations_data = []
        for installation in installations:
            installation_dict = installation.to_dict()
            installation_dict['id'] = installation.id
            installations_data.append(installation_dict)
        
        return jsonify({'installations': installations_data}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed/<instance_id>', methods=['GET'])
def get_installed_details(instance_id):
    """Get details of a specific installed integration"""
    try:
        installation = installed_integration_service.get_installed_by_id(instance_id)
        if not installation:
            return jsonify({'error': 'Installation not found'}), 404
        
        installation_data = installation.to_dict()
        installation_data['id'] = installation.id
        
        return jsonify({'installation': installation_data}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed/<instance_id>', methods=['PUT'])
def update_installed(instance_id):
    """Update an installed integration instance"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        # Only allow updating certain fields
        allowed_fields = {'config', 'credentials', 'is_active', 'instance_name'}
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        success = installed_integration_service.update_installed(instance_id, update_data)
        if not success:
            return jsonify({'error': 'Failed to update installation'}), 500
        
        # Return updated installation
        installation = installed_integration_service.get_installed_by_id(instance_id)
        installation_data = installation.to_dict()
        installation_data['id'] = installation.id
        
        return jsonify({
            'success': True,
            'message': 'Installation updated successfully',
            'installation': installation_data
        }), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed/<instance_id>', methods=['DELETE'])
def uninstall_module(instance_id):
    """Uninstall an integration instance"""
    try:
        success = installed_integration_service.uninstall(instance_id)
        if not success:
            return jsonify({'error': 'Failed to uninstall module'}), 500
        
        return jsonify({
            'success': True,
            'message': 'Module uninstalled successfully'
        }), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed/<instance_id>/test', methods=['POST'])
def test_integration(instance_id):
    """Test an installed integration by calling its test endpoint"""
    try:
        installation = installed_integration_service.get_installed_by_id(instance_id)
        if not installation:
            return jsonify({'error': 'Installation not found'}), 404
            
        # Convert to dict for the service
        integration_dict = installation.to_dict()
        # Ensure ID is included
        integration_dict['id'] = instance_id
        
        result = platform_auth_service.call_test_endpoint(
            installation.module_id, 
            integration_dict
        )
        
        return jsonify({
            'success': True,
            'result': result
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/installed/<instance_id>/sync', methods=['POST'])
def trigger_sync(instance_id):
    """Trigger a sync for a specific installed integration"""
    try:
        from models.integration_module import InstalledIntegration

        # Update sync status to pending
        success = installed_integration_service.update_sync_status(
            instance_id,
            'syncing'
        )

        if not success:
            return jsonify({'error': 'Failed to update sync status'}), 500

        # In a real implementation, this would trigger an actual sync process
        # For now, we'll just update the status to success
        success = installed_integration_service.update_sync_status(
            instance_id,
            'success'
        )

        if not success:
            return jsonify({'error': 'Failed to update sync status'}), 500

        return jsonify({
            'success': True,
            'message': 'Sync triggered successfully'
        }), 200

    except Exception as e:
        # Update status to error
        installed_integration_service.update_sync_status(instance_id, 'error')
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/installed/<instance_id>/renew', methods=['POST'])
def renew_token(instance_id):
    """Manually renews the access token for an integration"""
    try:
        installation = installed_integration_service.get_installed_by_id(instance_id)
        if not installation:
            return jsonify({'error': 'Installation not found'}), 404

        # Refresh token logic
        new_tokens = platform_auth_service.refresh_access_token(
            installation.module_id,
            installation.to_dict()
        )
        
        # Update installation with new tokens
        update_data = {
            'credentials': {
                'access_token': new_tokens.get('access_token'),
                'refresh_token': new_tokens.get('refresh_token'),
                'expires_in': new_tokens.get('expires_in'),
                # Keep existing shop_id and other credentials
                **(installation.credentials or {}),
            },
            'access_token': new_tokens.get('access_token'), # Also update top-level if used
            'refresh_token': new_tokens.get('refresh_token'),
            'expires_at': (datetime.utcnow() + timedelta(seconds=new_tokens.get('expires_in', 0))).isoformat() if new_tokens.get('expires_in') else None,
            'last_sync': datetime.utcnow().isoformat(), # Mark as synced/alive
            'refresh_error': None # Clear any previous error
        }
        # Update specific fields inside credentials to ensure persistence if schema uses JSONB
        if 'credentials' in update_data:
             current_creds = installation.credentials or {}
             current_creds.update(update_data['credentials'])
             update_data['credentials'] = current_creds

        installed_integration_service.update_installed(instance_id, update_data)
        
        return jsonify({
            'status': 'success',
            'message': 'Token renovado com sucesso'
        }), 200
        
    except Exception as e:
        # Log error in installation record
        installed_integration_service.update_installed(instance_id, {'refresh_error': str(e)})
        return jsonify({'error': str(e)}), 500


@marketplace_api_bp.route('/orders/list', methods=['POST'])
def get_orders_list():
    """
    Endpoint to fetch list of orders directly from an integrated platform (Live Query).
    This is used for viewing orders ('vendas') and does not persist data.

    Expects JSON: {
        "module_id": "shopee" (default),
        "instance_id": "optional_id",
        "filters": {
            "create_time_from": "timestamp",
            "create_time_to": "timestamp",
            "order_status": "status",
            "pagination_offset": 0,
            "pagination_entries_per_page": 50
        }
    }
    """
    try:
        data = request.get_json(silent=True) or {}

        # Priority to JSON, then query params
        instance_id = data.get('instance_id') or request.args.get('instance_id')
        module_id = data.get('module_id') or request.args.get('module_id') or "shopee"
        filters = data.get('filters') or {}

        # Call the generic platform API service
        from services.platform_api_service import platform_api_service
        result = platform_api_service.get_orders_list(
            instance_id=instance_id,
            module_id=module_id,
            filters=filters
        )

        # Check if there's an error in the result
        if result and isinstance(result, list) and len(result) > 0 and 'error' in result[0]:
            error_msg = result[0]['error']
            return ApiResponse.error(message=error_msg, errors=result[0], status_code=500)

        # Return the raw platform data directly
        return ApiResponse.success(data=result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return ApiResponse.error(message=str(e), status_code=500)


@marketplace_api_bp.route('/orders/detail', methods=['POST'])
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
        from services.platform_api_service import platform_api_service
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