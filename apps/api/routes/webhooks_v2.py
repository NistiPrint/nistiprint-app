from flask import Blueprint, request, jsonify
from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services import redis_queue_tasks
import logging
import json

logger = logging.getLogger("WebhookGateway")

webhooks_v2_bp = Blueprint('webhooks_v2', __name__, url_prefix='/api/v2/webhooks')

@webhooks_v2_bp.route('/<platform>/<instance_id>', methods=['POST'])
def receive_webhook(platform, instance_id):
    """
    Endpoint de recepção de webhooks integrado ao Flask.
    Salva o payload bruto no Supabase para processamento posterior pelo Worker.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        headers = dict(request.headers)
        
        # Detecta o evento simplificado
        evento = payload.get("topic") or payload.get("code") or payload.get("event_type") or "unknown"
        
        data = {
            "plataforma": platform,
            "instance_id": instance_id,
            "evento": str(evento),
            "payload": payload,
            "headers": headers,
            "status": "PENDENTE",
            "retry_count": 0,
            "next_retry_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Inserção rápida
        supabase_db.client.table("webhook_logs").insert(data).execute()
        
        return jsonify({"status": "accepted", "platform": platform}), 202

    except Exception as e:
        logger.error(f"Erro ao registrar webhook: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to log but accepted"}), 202

# --- Endpoints de Gerenciamento de Fila (Redis) ---

@webhooks_v2_bp.route('/queue/stats', methods=['GET'])
def get_queue_stats():
    """Retorna estatísticas das filas do Redis"""
    try:
        stats = redis_queue_tasks.get_queue_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_v2_bp.route('/queue/items', methods=['GET'])
def get_queue_items():
    """Retorna os itens de uma fila específica"""
    try:
        queue_name = request.args.get('queue', 'pendentes')
        limit = int(request.args.get('limit', 50))
        items = redis_queue_tasks.get_queue_items(queue_name, limit)
        return jsonify({'queue': queue_name, 'items': items}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_v2_bp.route('/queue/reprocess', methods=['POST'])
def reprocess_queue():
    """Move itens de falhas/dead-letter de volta para a fila principal"""
    try:
        source = request.json.get('source', 'dead_letter')
        count = redis_queue_tasks.move_items(source=source)
        return jsonify({'success': True, 'reprocessed': count}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_v2_bp.route('/queue/clear', methods=['DELETE'])
def clear_queue():
    """Limpa uma fila específica"""
    try:
        queue_name = request.args.get('queue')
        if not queue_name:
            return jsonify({'error': 'Nome da fila é obrigatório'}), 400
            
        redis_queue_tasks.clear_queue(queue_name)
        return jsonify({'success': True, 'message': f'Fila {queue_name} limpa'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
