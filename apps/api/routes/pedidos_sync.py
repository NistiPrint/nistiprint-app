from flask import Blueprint, request, jsonify
from nistiprint_shared.services.bling_status_sync_service import agendar_sync_status_batch, get_available_integrations_for_pedidos
from nistiprint_shared.database.supabase_db_service import supabase_db

pedidos_sync_bp = Blueprint('pedidos_sync', __name__)

@pedidos_sync_bp.route('/sync-bling-status', methods=['POST'])
def sync_bling_status():
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids') or []
    bling_integration_id = body.get('bling_integration_id')
    if not pedido_ids:
        return jsonify({'error': 'informe ao menos um pedido_id'}), 400
    if len(pedido_ids) > 500:
        return jsonify({'error': 'limite de 500 pedidos por lote'}), 400
        
    batch_id = agendar_sync_status_batch(pedido_ids, bling_integration_id)
    if not batch_id:
        return jsonify({'error': 'falha ao agendar lote'}), 500
        
    return jsonify({'batch_id': batch_id}), 202

@pedidos_sync_bp.route('/sync-bling-status/<batch_id>', methods=['GET'])
def sync_bling_status_progress(batch_id):
    res = supabase_db.table('sync_status_batches').select('*').eq('id', batch_id).execute()
    if not res.data:
        return jsonify({'error': 'lote não encontrado'}), 404
        
    return jsonify(res.data[0])

@pedidos_sync_bp.route('/sync-bling-status/<batch_id>/errors', methods=['GET'])
def sync_bling_status_errors(batch_id):
    res = supabase_db.table('sync_status_errors').select('*').eq('batch_id', batch_id).execute()
    return jsonify(res.data)

@pedidos_sync_bp.route('/sync-available-integrations', methods=['POST'])
def sync_available_integrations():
    """Lista as integrações disponíveis para sincronização dos pedidos selecionados"""
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids') or []
    if not pedido_ids:
        return jsonify({'error': 'informe ao menos um pedido_id'}), 400
    if len(pedido_ids) > 500:
        return jsonify({'error': 'limite de 500 pedidos por lote'}), 400
    
    integrations = get_available_integrations_for_pedidos(pedido_ids)
    return jsonify({'integrations': integrations}), 200

@pedidos_sync_bp.route('/sync-with-integration', methods=['POST'])
def sync_with_integration():
    """Sincroniza pedidos com uma integração específica"""
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids') or []
    integration_id = body.get('integration_id')
    module_id = body.get('module_id')
    
    if not pedido_ids:
        return jsonify({'error': 'informe ao menos um pedido_id'}), 400
    if not integration_id:
        return jsonify({'error': 'informe integration_id'}), 400
    if not module_id:
        return jsonify({'error': 'informe module_id'}), 400
    if len(pedido_ids) > 500:
        return jsonify({'error': 'limite de 500 pedidos por lote'}), 400
    
    # Rotear para o serviço apropriado baseado no module_id
    if module_id == 'bling':
        batch_id = agendar_sync_status_batch(pedido_ids, bling_integration_id=integration_id)
        if not batch_id:
            return jsonify({'error': 'falha ao agendar lote'}), 500
        return jsonify({'batch_id': batch_id}), 202
    else:
        # Para marketplaces (Shopee, Amazon, etc.), ainda não implementado
        return jsonify({'error': f'sincronização para {module_id} ainda não implementada'}), 501
