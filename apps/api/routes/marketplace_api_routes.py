from flask import jsonify, request, redirect, url_for
from datetime import datetime, timedelta
from nistiprint_shared.services.integration_module_service import integration_module_service
from nistiprint_shared.services.installed_integration_service import installed_integration_service
from nistiprint_shared.services.platform_auth_service import platform_auth_service
from nistiprint_shared.services.platform_api_service import platform_api_service
from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
from nistiprint_shared.database.supabase_db_service import supabase_db
from utils.api_response import ApiResponse
import os
from .marketplace_api_base import marketplace_api_bp

@marketplace_api_bp.route('/auth/init/<module_id>', methods=['POST'])
def init_auth(module_id):
    try:
        data = request.get_json()
        redirect_uri = data.get('redirect_uri') or (f"{os.environ.get('PUBLIC_URL', '').rstrip('/')}{url_for('marketplace_api.auth_callback', platform=module_id)}" if os.environ.get('PUBLIC_URL') else url_for('marketplace_api.auth_callback', platform=module_id, _external=True))
        auth_url = platform_auth_service.generate_auth_url(module_id, data.get('config', {}), redirect_uri, state=data.get('instance_id'))
        return jsonify({'auth_url': auth_url}) if auth_url else jsonify({'error': 'URL inválida'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/auth/exchange/<platform>', methods=['POST'])
def auth_exchange_manual(platform):
    try:
        data = request.get_json()
        inst = installed_integration_service.get_installed_by_id(data['instance_id'])
        if not inst: return jsonify({'error': 'Instalação não encontrada'}), 404
        tokens = platform_auth_service.exchange_code_for_token(platform, inst.config, data['code'], data.get('shop_id'))
        installed_integration_service.update_installed(data['instance_id'], {'credentials': {'access_token': tokens.get('access_token'), 'refresh_token': tokens.get('refresh_token'), 'expires_in': tokens.get('expires_in'), 'shop_id': data.get('shop_id')}, 'sync_status': 'active', 'is_active': True})
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/auth/callback/<platform>', methods=['GET'])
def auth_callback(platform):
    try:
        code, inst_id, shop_id = request.args.get('code'), request.args.get('state'), request.args.get('shop_id')
        if not code or not inst_id: return "Error", 400
        inst = installed_integration_service.get_installed_by_id(inst_id)
        if not inst: return "Error", 404
        tokens = platform_auth_service.exchange_code_for_token(platform, inst.config, code, shop_id)
        installed_integration_service.update_installed(inst_id, {'access_token': tokens.get('access_token'), 'refresh_token': tokens.get('refresh_token'), 'expires_at': (datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 0))).isoformat(), 'credentials': {'shop_id': shop_id}, 'sync_status': 'active', 'is_active': True})
        return redirect(f"{request.url_root.rstrip('/')}/configuracoes/integracoes?status=success&platform={platform}")
    except Exception as e:
        return str(e), 500

@marketplace_api_bp.route('/modules', methods=['GET'])
def get_available_modules():
    try:
        cat, tags = request.args.get('category'), request.args.get('tags')
        modules = integration_module_service.get_modules_by_category(cat) if cat else (integration_module_service.get_modules_by_tags(tags.split(',')) if tags else integration_module_service.get_all_modules())
        return jsonify({'modules': [{**m.to_dict(), 'id': m.id} for m in modules]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/modules/<module_id>', methods=['GET'])
def get_module_details(module_id):
    mod = integration_module_service.get_module_by_id(module_id)
    return jsonify({'module': {**mod.to_dict(), 'id': mod.id}}) if mod else (jsonify({'error': 'Not found'}), 404)

@marketplace_api_bp.route('/install', methods=['POST'])
def install_module():
    """Install a new instance of an integration module"""
    try:
        data = request.get_json()
        
        # Validation
        if not all([data.get('module_id'), data.get('instance_name'), data.get('user_id')]):
            return jsonify({'error': 'Faltando campos obrigatórios: module_id, instance_name, user_id'}), 400
            
        # Install the module
        instance_id = installed_integration_service.install_module(
            user_id=data['user_id'],
            module_id=data['module_id'],
            instance_name=data['instance_name'],
            config=data.get('config', {}),
            credentials=data.get('credentials', {}),
            instance_color=data.get('instance_color', '#64748b'),
            description=data.get('description')
        )
        
        # New fields: Update with linking and delegation
        update_fields = {}
        if data.get('parent_integration_id'):
            update_fields['parent_integration_id'] = data.get('parent_integration_id')
        if 'is_default' in data:
            update_fields['is_default'] = bool(data.get('is_default'))
        if data.get('functional_scopes'):
            update_fields['functional_scopes'] = data.get('functional_scopes')
            
        if update_fields:
            installed_integration_service.update_installed(instance_id, update_fields)
        
        # Original Auto-Provision logic (kept for compatibility)
        try:
            res = supabase_db.client.table('plataformas').select('id, nome').ilike('nome', f"%{data['module_id']}%").limit(1).execute()
            if res.data:
                p = res.data[0]
                res_canal = supabase_db.client.table('canais_venda').select('id').eq('nome', data['instance_name']).execute()
                canal_id = res_canal.data[0]['id'] if res_canal.data else supabase_db.client.table('canais_venda').insert({
                    'nome': data['instance_name'], 
                    'slug': f"{data['module_id']}-{int(datetime.utcnow().timestamp())}", 
                    'plataforma_id': p['id'], 
                    'ativo': True, 
                    'color': data.get('instance_color', '#64748b')
                }).execute().data[0]['id']
                
                if data.get('config', {}).get('bling_loja_id'):
                    try:
                        integracao_canal_service.criar_vinculo(
                            canal_venda_id=canal_id, 
                            bling_loja_id=int(data['config']['bling_loja_id']), 
                            plataforma_nome=p['nome'], 
                            integration_id=int(instance_id), 
                            is_primary=False, 
                            config_json={}
                        )
                    except:
                        pass
        except Exception as e:
            print(f"Erro no provisionamento automático: {e}")
        
        # Return the created instance
        inst = installed_integration_service.get_installed_by_id(instance_id)
        return jsonify({
            'success': True, 
            'instance_id': instance_id, 
            'installation': {**inst.to_dict(), 'id': inst.id}
        }), 201
    except Exception as e:
        print(f"Erro na instalação: {e}")
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/installed', methods=['GET'])
def get_installed_integrations():
    """Get all installed integrations, optionally filtered by module_id or category"""
    try:
        user_id = request.args.get('user_id')
        module_id = request.args.get('module_id')
        category = request.args.get('category')
        
        # Get all installations
        insts = installed_integration_service.get_all_installed(user_id=user_id)
        
        # Filter by module_id if provided
        if module_id:
            insts = [i for i in insts if i.module_id == module_id]
            
        # Filter by category if provided
        if category:
            from nistiprint_shared.services.integration_module_service import integration_module_service
            modules = integration_module_service.get_modules_by_category(category)
            module_ids = [m.id for m in modules]
            insts = [i for i in insts if i.module_id in module_ids]
            
        return jsonify({
            'installations': [{**i.to_dict(), 'id': i.id} for i in insts]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/installed/<instance_id>', methods=['GET', 'PUT', 'DELETE'])
def installed_crud(instance_id):
    """CRUD operations for a specific installed integration"""
    if request.method == 'GET':
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst:
            return jsonify({'error': 'Não encontrado'}), 404
        return jsonify({'installation': {**inst.to_dict(), 'id': inst.id}})
        
    if request.method == 'PUT':
        data = request.get_json()
        
        # Allowed fields for update
        update_data = {}
        allowed_fields = {
            'config', 'credentials', 'is_active', 'instance_name', 
            'parent_integration_id', 'is_default', 'functional_scopes',
            'instance_color', 'description'
        }
        
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
                
        if update_data:
            installed_integration_service.update_installed(instance_id, update_data)
            
        inst = installed_integration_service.get_installed_by_id(instance_id)
        return jsonify({
            'success': True, 
            'installation': {**inst.to_dict(), 'id': inst.id}
        })
        
    if request.method == 'DELETE':
        installed_integration_service.uninstall(instance_id)
        return jsonify({'success': True})
        
    return jsonify({'error': 'Método não permitido'}), 405

@marketplace_api_bp.route('/bling/config-helpers/<instance_id>', methods=['GET'])
def get_bling_config_helpers(instance_id):
    """Helper to fetch Bling statuses and stores for configuration UI"""
    try:
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != 'bling':
            return jsonify({'error': 'Instância Bling não encontrada'}), 404
            
        from nistiprint_shared.services.bling.bling_client_updated import BlingClient
        
        # Convert InstalledIntegration to account_data dict format BlingClient expects
        account_data = inst.to_dict()
        account_data['id'] = inst.id
        # Client needs these top-level or in credentials
        if 'access_token' not in account_data and inst.access_token:
            account_data['access_token'] = inst.access_token
        if 'refresh_token' not in account_data and inst.refresh_token:
            account_data['refresh_token'] = inst.refresh_token
            
        client = BlingClient(account_data)
        
        return jsonify({
            'situacoes': client.get_situacoes(modulo="vendas"),
            'lojas': client.get_stores()
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/bling/orders/search', methods=['GET'])
def search_bling_orders():
    """Search orders in a specific Bling instance"""
    try:
        instance_id = request.args.get('instance_id')
        status_id = request.args.get('status_id')
        store_id = request.args.get('store_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not instance_id:
            return jsonify({'error': 'instance_id é obrigatório'}), 400
            
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != 'bling':
            return jsonify({'error': 'Instância Bling não encontrada'}), 404
            
        from nistiprint_shared.services.bling.bling_client_updated import BlingClient
        
        account_data = inst.to_dict()
        account_data['id'] = inst.id
        if inst.access_token: account_data['access_token'] = inst.access_token
        if inst.refresh_token: account_data['refresh_token'] = inst.refresh_token
            
        client = BlingClient(account_data)
        
        # Default dates if not provided
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.utcnow().strftime('%Y-%m-%d')
            
        orders = client.get_orders_by_status(
            status_id=status_id,
            store_id=store_id,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({'orders': orders}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/bling/orders/import', methods=['POST'])
def import_bling_orders():
    """Import selected orders from Bling to the system"""
    try:
        data = request.get_json()
        instance_id = data.get('instance_id')
        order_ids = data.get('order_ids', []) # List of Bling internal order IDs
        
        if not instance_id or not order_ids:
            return jsonify({'error': 'instance_id e order_ids são obrigatórios'}), 400
            
        inst = installed_integration_service.get_installed_by_id(instance_id)
        if not inst or inst.module_id != 'bling':
            return jsonify({'error': 'Instância Bling não encontrada'}), 404
            
        from nistiprint_shared.services.bling.bling_client_updated import BlingClient
        from nistiprint_shared.services.order_sync_service import order_sync_service
        from nistiprint_shared.services.bling_order_processing_service import BlingOrderProcessingService
        
        account_data = inst.to_dict()
        account_data['id'] = inst.id
        if inst.access_token: account_data['access_token'] = inst.access_token
        if inst.refresh_token: account_data['refresh_token'] = inst.refresh_token
            
        client = BlingClient(account_data)
        processor = BlingOrderProcessingService()
        
        results = []
        for oid in order_ids:
            try:
                # Fetch full details
                full_order = client.get_order(oid)
                if not full_order:
                    results.append({'id': oid, 'status': 'error', 'message': 'Não foi possível obter detalhes do pedido'})
                    continue
                
                # Sync using standard service
                sync_result = order_sync_service.sync_bling_order(full_order)
                
                # Save to legacy DB for compatibility
                processor._save_order_to_db(full_order)
                
                results.append({
                    'id': oid, 
                    'status': 'success', 
                    'numero': full_order.get('numero'),
                    'internal_id': sync_result.get('id') if sync_result else None
                })
            except Exception as oid_err:
                results.append({'id': oid, 'status': 'error', 'message': str(oid_err)})
                
        return jsonify({'results': results}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/installed/<instance_id>/test', methods=['POST'])
def test_integration(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    return jsonify({'success': True, 'result': platform_auth_service.call_test_endpoint(inst.module_id, {**inst.to_dict(), 'id': instance_id})}) if inst else (jsonify({'error': 'Not found'}), 404)

@marketplace_api_bp.route('/installed/<instance_id>/sync', methods=['POST'])
def trigger_sync(instance_id):
    installed_integration_service.update_sync_status(instance_id, 'syncing')
    installed_integration_service.update_sync_status(instance_id, 'success')
    return jsonify({'success': True})

@marketplace_api_bp.route('/installed/<instance_id>/renew', methods=['POST'])
def renew_token(instance_id):
    inst = installed_integration_service.get_installed_by_id(instance_id)
    try:
        tokens = platform_auth_service.refresh_access_token(inst.module_id, inst.to_dict())
        update = {'credentials': {**(inst.credentials or {}), 'access_token': tokens.get('access_token'), 'refresh_token': tokens.get('refresh_token'), 'expires_in': tokens.get('expires_in')}, 'access_token': tokens.get('access_token'), 'refresh_token': tokens.get('refresh_token'), 'expires_at': (datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 0))).isoformat(), 'refresh_error': None}
        installed_integration_service.update_installed(instance_id, update)
        return jsonify({'status': 'success'})
    except Exception as e:
        installed_integration_service.update_installed(instance_id, {'refresh_error': str(e)})
        return jsonify({'error': str(e)}), 500

@marketplace_api_bp.route('/orders/list', methods=['POST'])
def get_orders_list():
    data = request.get_json(silent=True) or {}
    result = platform_api_service.get_orders_list(instance_id=data.get('instance_id') or request.args.get('instance_id'), module_id=data.get('module_id') or request.args.get('module_id') or "shopee", filters=data.get('filters', {}))
    return ApiResponse.success(data=result) if not (isinstance(result, list) and result and 'error' in result[0]) else ApiResponse.error(message=result[0]['error'], errors=result[0], status_code=500)

@marketplace_api_bp.route('/orders/detail', methods=['POST'])
def get_order_detail():
    data = request.get_json(silent=True) or {}
    order_sn = data.get('order_sn_list') or request.args.get('order_sn_list')
    if not order_sn: return ApiResponse.error(message="Required", status_code=400)
    result = platform_api_service.get_order_detail([sn.strip() for sn in order_sn.split(',') if sn.strip()], instance_id=data.get('instance_id') or request.args.get('instance_id'), module_id=data.get('module_id') or request.args.get('module_id') or "shopee")
    return ApiResponse.success(data=result) if not (result.get("error") and result.get("error") != "") else ApiResponse.error(message=result["error"], errors=result, status_code=500)

@marketplace_api_bp.route('/instances', methods=['GET'])
def get_marketplace_instances():
    """Get all marketplace instances (non-Bling), optionally filtered by active status"""
    try:
        from nistiprint_shared.services.installed_integration_service import installed_integration_service
        
        active = request.args.get('active', 'false').lower() == 'true'
        
        # Get all installed integrations
        insts = installed_integration_service.get_all_installed()
        
        # Filter out Bling (ERP) instances
        insts = [i for i in insts if i.module_id != 'bling']
        
        # Filter by active status if requested
        if active:
            insts = [i for i in insts if i.is_active]
        
        return jsonify({
            'data': [{
                'id': i.id,
                'module_id': i.module_id,
                'instance_name': i.instance_name,
                'is_active': i.is_active,
            } for i in insts]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
