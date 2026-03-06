from flask import Blueprint, request, jsonify
from nistiprint_shared.services.webhook_service import webhook_service
from nistiprint_shared.services.redis_queue_tasks import get_redis_client, BLING_WEBHOOK_QUEUE, BLING_WEBHOOK_DEAD_LETTER, BLING_WEBHOOK_FALHAS
import json
import os

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/api/v2/webhooks')

@webhooks_bp.route('/queue/stats', methods=['GET'])
def get_queue_stats():
    """
    Retorna estatísticas das filas do Redis
    """
    try:
        r = get_redis_client()
        stats = {
            'pendentes': r.llen(BLING_WEBHOOK_QUEUE),
            'dead_letter': r.llen(BLING_WEBHOOK_DEAD_LETTER),
            'falhas': r.llen(BLING_WEBHOOK_FALHAS)
        }
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_bp.route('/queue/reprocess', methods=['POST'])
def reprocess_queue():
    """
    Move itens da fila de falhas/dead-letter de volta para a fila principal
    """
    try:
        r = get_redis_client()
        source = request.json.get('source', 'dead_letter')
        queue_name = BLING_WEBHOOK_DEAD_LETTER if source == 'dead_letter' else BLING_WEBHOOK_FALHAS

        count = 0
        while True:
            item = r.lpop(queue_name)
            if not item:
                break
            r.rpush(BLING_WEBHOOK_QUEUE, item)
            count += 1

        return jsonify({'success': True, 'reprocessed': count}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_bp.route('/queue/worker-logs', methods=['GET'])
def get_worker_logs():
    """
    Tenta ler as últimas linhas do log do worker
    """
    try:
        log_path = 'logs/worker.log'
        if not os.path.exists(log_path):
            return jsonify({'logs': 'Arquivo de log não encontrado no servidor.'}), 200

        with open(log_path, 'r') as f:
            lines = f.readlines()[-100:]
            return jsonify({'logs': ''.join(lines)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@webhooks_bp.route('/<platform>', methods=['POST'])
@webhooks_bp.route('/<platform>/<instance_id>', methods=['POST'])
def receive_webhook(platform, instance_id=None):
    """
    Unified endpoint for receiving webhooks from any platform
    """
    try:
        # Get headers and payload
        headers = dict(request.headers)
        
        # Try to get JSON payload, fallback to data if not JSON
        if request.is_json:
            payload = request.get_json()
        else:
            payload = {"raw_data": request.get_data(as_text=True)}

        # Log the webhook for later processing
        log_id = webhook_service.log_webhook(
            plataforma=platform,
            payload=payload,
            headers=headers,
            instance_id=instance_id
        )

        # Immediate response to the platform (usually required within seconds)
        return jsonify({
            'success': True,
            'message': 'Webhook received and logged',
            'log_id': log_id
        }), 200

    except Exception as e:
        print(f"Error receiving webhook for {platform}: {e}")
        # Even on error, we might want to return 200 to some platforms to prevent retries 
        # of bad payloads, but for now 500 is safer for debugging.
        return jsonify({'error': str(e)}), 500

@webhooks_bp.route('/logs', methods=['GET'])
def get_webhook_logs():
    """
    Get recent webhook logs for the monitor
    """
    try:
        # Fetch last 50 logs
        response = webhook_service.table.select("*").order('created_at', descending=True).limit(50).execute()
        return jsonify({'logs': response.data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500





