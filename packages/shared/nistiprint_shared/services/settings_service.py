from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db

class SettingsService:
    """Service for managing application settings (tokens, configs) in Supabase."""

    def __init__(self):
        self.table = supabase_db.table('configuracoes_aplicacao')

    def create(self, settings_data):
        """Create new settings entry."""
        data = {
            'name': settings_data['name'],
            'versao': settings_data['versao'],
            'client_id': settings_data['client_id'],
            'client_secret': settings_data['client_secret'],
            'access_token': settings_data['access_token'],
            'refresh_token': settings_data['refresh_token'],
            'expires_in': settings_data['expires_in'],
            'id_custom_column_bling': settings_data['id_custom_column_bling'],
            'created_at': settings_data.get('created_at', datetime.utcnow()).isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = str(result.get('id'))
            return result
        return None

    def get_by_name_and_version(self, name: str, versao: str):
        """Get settings by name and version (most recent first)."""
        response = self.table.select("*").eq('name', name).eq('versao', versao).order('created_at', desc=True).limit(1).execute()

        if response.data:
            settings = dict(response.data[0])
            settings['id'] = str(settings.get('id'))
            return settings
        return None

    def get_by_name(self, name: str):
        """Get the most recent settings by name."""
        response = self.table.select("*").eq('name', name).order('created_at', desc=True).limit(1).execute()

        if response.data:
            settings = dict(response.data[0])
            settings['id'] = str(settings.get('id'))
            return settings
        return None

    def update_token(self, settings_id: str, access_token: str, refresh_token: str, expires_in: int):
        """Update token data for a settings entry."""
        update_data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in,
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.update(update_data).eq('id', settings_id).execute()

        # Return updated settings
        updated = self.get_by_id(settings_id)
        return updated if updated else None

    def get_by_id(self, settings_id: str):
        """Get settings by ID."""
        response = self.table.select("*").eq('id', settings_id).execute()
        if response.data:
            settings = dict(response.data[0])
            settings['id'] = str(settings.get('id'))
            return settings
        return None

    def get_all(self):
        """Get all settings."""
        response = self.table.select("*").order('name').execute()
        settings = []
        for row in response.data:
            setting = dict(row)
            setting['id'] = str(setting.get('id'))
            settings.append(setting)
        return settings

# Global instance for use throughout the application
settings_service = SettingsService()

