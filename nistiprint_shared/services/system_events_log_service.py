from nistiprint_shared.database.supabase_db_service import supabase_db
import json

class SystemEventsLogService:
    def __init__(self):
        self.table = supabase_db.table('system_events_log')

    def log_event(self, event_type: str, details: dict, user_id: str = 'System'):
        try:
            # Converte todo o dicionário de detalhes para uma string JSON
            details_json = json.dumps(details, default=str)
            
            payload = {
                'event_type': event_type,
                'details': details_json,
                'user_id': user_id,
                'status': 'OPEN'
            }
            self.table.insert(payload).execute()
        except Exception as e:
            print(f"CRITICAL: Falha ao registrar evento de sistema no log: {e}")

system_events_log_service = SystemEventsLogService()

