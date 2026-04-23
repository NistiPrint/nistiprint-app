from services.firebase.firestore_client import firestore_client
from datetime import datetime

class AppConfigService:
    """Service for managing general application configurations in Firestore."""

    def __init__(self):
        self.collection = firestore_client.collection('app_configurations')

    def get_config(self, key: str):
        """Get a configuration value by its key."""
        doc = self.collection.document(key).get()
        if doc.exists:
            return doc.to_dict().get('value')
        return None

    def set_config(self, key: str, value):
        """Set a configuration value for a given key."""
        data = {
            'key': key,
            'value': value,
            'updated_at': datetime.utcnow()
        }
        self.collection.document(key).set(data)
        return data

# Global instance for use throughout the application
app_config_service = AppConfigService()
