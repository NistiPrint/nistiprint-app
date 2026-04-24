from datetime import datetime
from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client

class SettingsService:
    """Service for managing application settings (tokens, configs) in Firestore."""

    def __init__(self):
        self.collection = firestore_client.collection('settings')

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
            'created_at': settings_data.get('created_at', datetime.utcnow()),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id
        return data

    def get_by_name_and_version(self, name: str, versao: str):
        """Get settings by name and version (most recent first)."""
        docs = self.collection.where('name', '==', name).where('versao', '==', versao).order_by('created_at', direction=firestore.Query.DESCENDING).limit(1).stream()

        for doc in docs:
            settings = doc.to_dict()
            settings['id'] = doc.id
            return settings
        return None

    def get_by_name(self, name: str):
        """Get the most recent settings by name."""
        docs = self.collection.where('name', '==', name).order_by('created_at', direction=firestore.Query.DESCENDING).limit(1).stream()

        for doc in docs:
            settings = doc.to_dict()
            settings['id'] = doc.id
            return settings
        return None

    def update_token(self, settings_id: str, access_token: str, refresh_token: str, expires_in: int):
        """Update token data for a settings entry."""
        update_data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in,
            'updated_at': datetime.utcnow()
        }

        self.collection.document(settings_id).update(update_data)

        # Return updated settings
        updated = self.get_by_id(settings_id)
        return updated if updated else None

    def get_by_id(self, settings_id: str):
        """Get settings by ID."""
        doc = self.collection.document(settings_id).get()
        if doc.exists:
            settings = doc.to_dict()
            settings['id'] = doc.id
            return settings
        return None

    def get_all(self):
        """Get all settings."""
        docs = self.collection.order_by('name').stream()
        settings = []
        for doc in docs:
            setting = doc.to_dict()
            setting['id'] = doc.id
            settings.append(setting)
        return settings

# Global instance for use throughout the application
settings_service = SettingsService()
