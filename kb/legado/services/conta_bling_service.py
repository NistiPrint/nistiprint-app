from services.firebase.firestore_client import firestore_client
from datetime import datetime

class ContaBlingService:
    """Service for managing Bling accounts (contas Bling) in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            # Usar a coleção existente bling_accounts para manter compatibilidade
            self._collection = firestore_client.collection('bling_accounts')
        return self._collection

    def get_all(self):
        """Get all Bling accounts ordered by name."""
        docs = self.collection.order_by('account_name').stream()

        accounts = []
        for doc in docs:
            account_data = doc.to_dict()
            account_data['id'] = doc.id
            accounts.append(account_data)

        return accounts

    def get_by_id(self, account_id: str):
        """Get Bling account by ID."""
        doc = self.collection.document(account_id).get()
        if doc.exists:
            account = doc.to_dict()
            account['id'] = doc.id
            return account
        return None

    def get_by_cnpj(self, cnpj: str):
        """Get Bling account by CNPJ."""
        docs = self.collection.where('cnpj', '==', cnpj).stream()
        for doc in docs:
            account = doc.to_dict()
            account['id'] = doc.id
            return account
        return None

    def create(self, account_data):
        """Create a new Bling account."""
        # Check CNPJ uniqueness
        existing = self.get_by_cnpj(account_data['cnpj'])
        if existing:
            raise ValueError(f"Bling account with CNPJ '{account_data['cnpj']}' already exists")

        # Prepare data - adaptar para os campos existentes
        data = {
            'account_name': account_data['account_name'],
            'cnpj': account_data['cnpj'],
            'client_id': account_data.get('client_id'),
            'client_secret': account_data.get('client_secret'),
            'access_token': account_data.get('access_token'),
            'refresh_token': account_data.get('refresh_token'),
            'expires_in': account_data.get('expires_in'),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id

        return data

    def update(self, account_id: str, account_data):
        """Update an existing Bling account."""
        # Check CNPJ uniqueness if being updated
        if 'cnpj' in account_data:
            existing = self.get_by_cnpj(account_data['cnpj'])
            if existing and existing['id'] != account_id:
                raise ValueError(f"Bling account with CNPJ '{account_data['cnpj']}' already exists")

        # Get existing account
        existing = self.get_by_id(account_id)
        if not existing:
            raise ValueError(f"Bling account with ID '{account_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow()}

        # Mapear campos para os nomes existentes
        field_mappings = {
            'account_name': 'account_name',
            'cnpj': 'cnpj',
            'client_id': 'client_id',
            'client_secret': 'client_secret',
            'access_token': 'access_token',
            'refresh_token': 'refresh_token',
            'expires_in': 'expires_in'
        }

        for field, key in field_mappings.items():
            if field in account_data:
                update_data[key] = account_data[field]

        self.collection.document(account_id).update(update_data)

        # Return updated account
        return self.get_by_id(account_id)

    def delete(self, account_id: str):
        """Delete a Bling account."""
        existing = self.get_by_id(account_id)
        if not existing:
            raise ValueError(f"Bling account with ID '{account_id}' not found")

        self.collection.document(account_id).delete()
        return True

    def count(self):
        """Get total count of Bling accounts."""
        docs = self.collection.stream()
        return len(list(docs))

    def update_tokens(self, account_id: str, access_token: str, refresh_token: str = None, expires_in: int = None):
        """Update tokens for a Bling account."""
        update_data = {
            'access_token': access_token,
            'updated_at': datetime.utcnow()
        }

        if refresh_token:
            update_data['refresh_token'] = refresh_token
        if expires_in:
            update_data['expires_in'] = expires_in

        self.collection.document(account_id).update(update_data)
        return self.get_by_id(account_id)

# Global instance for use throughout the application
conta_bling_service = ContaBlingService()
