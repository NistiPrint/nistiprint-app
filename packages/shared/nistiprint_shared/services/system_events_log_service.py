import json

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.file_archive_service import file_archive_service

class SystemEventsLogService:
    def __init__(self):
        self.table = supabase_db.table('system_events_log')

    def log_event(self, event_type: str, details: dict, user_id: str = 'System'):
        try:
            payload = {
                'event_type': event_type,
                'details': details,
                'user_id': user_id,
                'status': 'OPEN',
            }
            archive_path = file_archive_service.append('system_events_log', payload)
            print(f"[system-events-log] archived to {archive_path}")
        except Exception as e:
            print(f"CRITICAL: Falha ao registrar evento de sistema no log: {e}")
            try:
                details_json = json.dumps(details, default=str)
                self.table.insert({
                    'event_type': event_type,
                    'details': details_json,
                    'user_id': user_id,
                    'status': 'OPEN',
                }).execute()
            except Exception as db_error:
                print(f"CRITICAL: Falha ao persistir evento de sistema no banco: {db_error}")

system_events_log_service = SystemEventsLogService()

