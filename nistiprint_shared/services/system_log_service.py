from typing import Any, Dict, Optional
from nistiprint_shared.database.supabase_db_service import supabase_db

class SystemLogService:
    """Serviço centralizado para logs de eventos e erros do sistema."""
    
    def __init__(self):
        self.table_name = 'system_events_log'

    def log(self, category: str, message: str, severity: str = 'ERROR', 
            action: Optional[str] = None, reference_id: Optional[str] = None, 
            metadata: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None):
        """
        Registra um evento no log do sistema.
        """
        try:
            data = {
                'category': category,
                'message': message,
                'severity': severity,
                'action': action,
                'reference_id': str(reference_id) if reference_id else None,
                'metadata': metadata or {},
                'user_id': str(user_id) if user_id else None
            }
            
            supabase_db.insert(self.table_name, data)
        except Exception as e:
            # Fallback para console se o próprio log falhar
            print(f"CRITICAL: Falha ao registrar log no banco: {e}")
            print(f"Log original: {category} - {message}")

    def log_estoque_error(self, message: str, action: str, reference_id: str, 
                           metadata: Dict[str, Any], user_id: Optional[str] = None):
        """Helper específico para erros de estoque."""
        self.log(
            category='ESTOQUE',
            message=message,
            severity='ERROR',
            action=action,
            reference_id=reference_id,
            metadata=metadata,
            user_id=user_id
        )

system_log_service = SystemLogService()

