from flask import Blueprint, request, jsonify
from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

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
        # Mesmo com erro de log, retornamos 200/202 para a plataforma não desativar o webhook
        return jsonify({"status": "error", "message": "Failed to log but accepted"}), 202





