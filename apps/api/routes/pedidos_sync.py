from flask import Blueprint, request, jsonify
from nistiprint_shared.services.bling_status_sync_service import agendar_sync_status_batch
from nistiprint_shared.database.supabase_db_service import supabase_db

pedidos_sync_bp = Blueprint('pedidos_sync', __name__)

@pedidos_sync_bp.route('/sync-bling-status', methods=['POST'])
def sync_bling_status():
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids') or []
    if not pedido_ids:
        return jsonify({'error': 'informe ao menos um pedido_id'}), 400
    if len(pedido_ids) > 500:
        return jsonify({'error': 'limite de 500 pedidos por lote'}), 400
        
    batch_id = agendar_sync_status_batch(pedido_ids)
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
