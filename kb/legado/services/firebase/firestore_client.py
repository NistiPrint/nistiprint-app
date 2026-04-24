import os
from firebase_admin import firestore

class FirestoreClient:
    """Centralized client for Firestore operations."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirestoreClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._db = None
            self._database_id = '(default)'
            self._database_id = os.environ.get('FIRESTORE_DATABASE_ID', '(default)')            
            environment = os.environ.get('FLASK_ENV', 'production')
            print(environment)
            if environment == 'development':
                self._database_id = 'homolog'
            print(f"FirestoreClient initialized with database_id: {self._database_id}")


    def collection(self, collection_name: str):
        """Gets a collection reference."""
        return self.db.collection(collection_name)

    def document(self, collection_name: str, document_id: str = None):
        """Gets a document reference."""
        if document_id:
            return self.db.collection(collection_name).document(document_id)
        return self.db.collection(collection_name).document()

    @property
    def db(self):
        """Returns the Firestore database client, initializing it if needed."""
        if self._db is None:
            try:
                self._db = firestore.client(database_id=self._database_id)
            except ValueError:
                # Firebase not initialized yet, try to initialize it
                from services.firebase.firebase import initialize_firebase
                if initialize_firebase():
                    self._db = firestore.client(database_id=self._database_id)
                else:
                    raise ValueError("Firebase app not initialized and failed to initialize")
        return self._db

    @property
    def client(self):
        """Returns the Firestore client."""
        return self.db

# Global instance for use throughout the application
firestore_client = FirestoreClient()
