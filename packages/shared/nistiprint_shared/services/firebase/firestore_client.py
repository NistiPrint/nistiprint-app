import os
import warnings

class FirestoreClient:
    """Centralized client for Firestore operations.

    NOTE: This application now uses only Supabase for data storage.
    This class is kept for compatibility purposes only and will raise
    an exception if any Firestore operations are attempted.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirestoreClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            print("WARNING: FirestoreClient is deprecated. This application now uses only Supabase for data storage.")
            warnings.warn(
                "FirestoreClient is deprecated. This application now uses only Supabase for data storage.",
                DeprecationWarning
            )

    def collection(self, collection_name: str):
        """Gets a collection reference."""
        raise RuntimeError(
            f"Firestore operations are disabled. "
            f"Collection '{collection_name}' should be replaced with a Supabase table."
        )

    def document(self, collection_name: str, document_id: str = None):
        """Gets a document reference."""
        raise RuntimeError(
            f"Firestore operations are disabled. "
            f"Document operations on '{collection_name}' should be replaced with Supabase operations."
        )

    @property
    def db(self):
        """Returns the Firestore database client."""
        raise RuntimeError(
            "Firestore operations are disabled. Use Supabase instead."
        )

    @property
    def client(self):
        """Returns the Firestore client."""
        raise RuntimeError(
            "Firestore operations are disabled. Use Supabase instead."
        )

# Global instance for use throughout the application
firestore_client = FirestoreClient()

