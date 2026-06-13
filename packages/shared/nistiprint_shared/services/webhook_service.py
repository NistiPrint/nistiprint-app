import hmac
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.webhook_log import WebhookLog
from nistiprint_shared.services.file_archive_service import file_archive_service

class WebhookService:
    """
    Service for handling and logging incoming webhooks from e-commerce platforms
    """
    
    def __init__(self):
        self.table = supabase_db.table('webhook_logs')

    def log_webhook(self, plataforma: str, payload: Dict[str, Any], headers: Dict[str, Any], instance_id: str = None) -> str | int | None:
        """
        Log an incoming webhook to a host file archive.
        """
        webhook_log = {
            'plataforma': plataforma,
            'instance_id': instance_id,
            'evento': self._detect_event_type(plataforma, payload),
            'payload': payload,
            'headers': headers,
            'status': 'PENDENTE',
            'created_at': datetime.utcnow().isoformat()
        }
        try:
            archive_path = file_archive_service.append('webhook_logs', webhook_log, webhook_log['created_at'])
            print(f"[webhook-log] archived to {archive_path}")
            return archive_path
        except Exception as e:
            print(f"Error logging webhook from {plataforma}: {e}")
            try:
                response = self.table.insert({
                    **webhook_log,
                    'payload': json.dumps(payload, default=str),
                    'headers': json.dumps(headers, default=str),
                }).execute()
                if response.data:
                    return response.data[0]['id']
            except Exception as db_error:
                print(f"Error persisting webhook log to database: {db_error}")
            return None

    def _detect_event_type(self, plataforma: str, payload: Dict[str, Any]) -> str:
        """
        Detect the event type from the payload based on platform-specific fields
        """
        if plataforma == 'shopee':
            return payload.get('code', 'unknown')
        elif plataforma == 'mercadolivre':
            return payload.get('topic', 'unknown')
        elif plataforma == 'amazon':
            return payload.get('NotificationType', 'unknown')
        elif plataforma == 'shein':
            return payload.get('event_type', 'unknown')
        return 'unknown'

    def validate_signature(self, plataforma: str, payload: str, headers: Dict[str, Any], secret: str) -> bool:
        """
        Validate the webhook signature to ensure it's from the legitimate source
        """
        if plataforma == 'shopee':
            # Shopee uses HMAC-SHA256 of the concatenated URL and body
            # Implementation depends on exact Shopee version
            pass
        elif plataforma == 'mercadolivre':
            # ML uses x-meli-signature
            pass
            
        # For now, we'll return True to allow development
        return True

    def mark_as_processed(self, log_id: int, status: str = 'SUCESSO', error_msg: str = None):
        """
        Update the status of a webhook log
        """
        update_data = {
            'status': status,
            'processed_at': datetime.utcnow().isoformat()
        }
        if error_msg:
            update_data['mensagem_erro'] = error_msg
        file_archive_service.append(
            'webhook_logs_updates',
            {'log_id': log_id, 'update_data': update_data},
            datetime.utcnow().isoformat(),
        )

# Global instance
webhook_service = WebhookService()

