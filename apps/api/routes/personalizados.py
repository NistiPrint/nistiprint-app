"""
Endpoints para gestão de pedidos personalizados com IA (Refatorado - Parte C).
"""

from flask import Blueprint, request, jsonify, g
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.ai_personalization_service import (
    processar_batch_ia, 
    _listar_pendentes,
    process_orders,
    get_logs_by_order_sn,
    get_orders_with_chats
)
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("PersonalizadosAPI")

personalizados_bp = Blueprint('personalizados', __name__)

@personalizados_bp.route('', methods=['GET'])
def listar_personalizados():
    """Lista pedidos com itens personalizados."""
    try:
        order_sn = request.args.get('order_sn')
        limit = request.args.get('limit', type=int)
        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        return ApiResponse.success({'orders': orders, 'total': len(orders)})
    except Exception as e:
        return ApiResponse.error(str(e), 500)

@personalizados_bp.route('/processar', methods=['POST'])
def processar():
    """Inicia processamento em lote (Batch IA)."""
    body = request.get_json() or {}
    pedido_ids = body.get('pedido_ids')
    limit = body.get('limit', 100)
    
    # Se não informar IDs, busca pendentes
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
    """Consulta progresso do batch."""
    res = supabase_db.table('execucoes_ai_batch').select('*').eq('id', batch_id).execute()
    if not res.data:
        return jsonify({'error': 'batch não encontrado'}), 404
        
    return jsonify(res.data[0])

@personalizados_bp.route('/processar/<batch_id>/itens', methods=['GET'])
def itens_batch(batch_id):
    """Lista detalhes dos itens de um batch."""
    res = supabase_db.table('execucoes_ai_item').select('*').eq('batch_id', batch_id).execute()
    return jsonify(res.data)

@personalizados_bp.route('/logs/<order_sn>', methods=['GET'])
def get_logs(order_sn):
    """Retorna logs de execução para um pedido."""
    logs = get_logs_by_order_sn(order_sn)
    return ApiResponse.success({'logs': logs, 'total': len(logs)})

@personalizados_bp.route('/reprocessar/<order_sn>', methods=['POST'])
def reprocessar(order_sn):
    """Reprocessa um pedido individualmente (síncrono)."""
    success, message = process_orders(order_sn=order_sn)
    return ApiResponse.success({'success': success, 'message': message})
