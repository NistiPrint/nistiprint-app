import hmac
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.webhook_log import WebhookLog

class WebhookService:
    """
    Service for handling and logging incoming webhooks from e-commerce platforms
    """
    
    def __init__(self):
        self.table = supabase_db.table('webhook_logs')

    def log_webhook(self, plataforma: str, payload: Dict[str, Any], headers: Dict[str, Any], instance_id: str = None) -> int:
        """
        Log an incoming webhook to the database
        """
        try:
            # Detect event type if possible based on platform
            evento = self._detect_event_type(plataforma, payload)
            
            webhook_log = {
                'plataforma': plataforma,
                'instance_id': instance_id,
                'evento': evento,
                'payload': payload,
                'headers': headers,
                'status': 'PENDENTE',
                'created_at': datetime.utcnow().isoformat()
            }
            
            response = self.table.insert(webhook_log).execute()
            
            if response.data:
                return response.data[0]['id']
            return None
        except Exception as e:
            print(f"Error logging webhook from {plataforma}: {e}")
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
            
        self.table.update(update_data).eq('id', log_id).execute()

# Global instance
webhook_service = WebhookService()

