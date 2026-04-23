from flask import Blueprint, request, jsonify, g
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.ai_personalization_service import processar_batch_ia, _listar_pendentes

personalizados_bp = Blueprint('personalizados', __name__)

@personalizados_bp.route('/processar', methods=['POST'])
def processar():
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids')
    limit = body.get('limit', 100)
    
    if not pedido_ids:
        pedido_ids = _listar_pendentes(limit)
        
    if not pedido_ids:
        return jsonify({'message': 'nada a processar'}), 200
        
    batch_res = supabase_db.table('execucoes_ai_batch').insert({
        'pedido_ids': pedido_ids,
        'total': len(pedido_ids),
        'status': 'PENDENTE',
        'iniciado_por': getattr(g, 'user_email', None)
    }).execute()
    
    if not batch_res.data:
        return jsonify({'error': 'falha ao criar batch'}), 500
        
    batch_id = batch_res.data[0]['id']
    processar_batch_ia.delay(batch_id)
    
    return jsonify({'batch_id': batch_id}), 202

@personalizados_bp.route('/processar/<batch_id>', methods=['GET'])
def progresso(batch_id):
    res = supabase_db.table('execucoes_ai_batch').select('*').eq('id', batch_id).execute()
    if not res.data:
        return jsonify({'error': 'batch não encontrado'}), 404
        
    return jsonify(res.data[0])

@personalizados_bp.route('/processar/<batch_id>/itens', methods=['GET'])
def itens_batch(batch_id):
    res = supabase_db.table('execucoes_ai_item').select('*').eq('batch_id', batch_id).execute()
    return jsonify(res.data)
