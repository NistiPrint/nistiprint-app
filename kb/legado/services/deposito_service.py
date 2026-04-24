from services.firebase.firestore_client import firestore_client
from datetime import datetime
from typing import List, Dict, Any

class DepositoService:
    """Service for managing warehouses/depots (depósitos) in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('depositos')
        return self._collection

    def get_all(self):
        """Get all depósitos ordered by name."""
        docs = self.collection.order_by('nome').stream()

        deposits = []
        for doc in docs:
            deposit_data = doc.to_dict()
            deposit_data['id'] = doc.id
            deposits.append(deposit_data)

        return deposits

    def get_by_id(self, deposit_id: str):
        """Get depósito by ID."""
        doc = self.collection.document(deposit_id).get()
        if doc.exists:
            deposit = doc.to_dict()
            deposit['id'] = doc.id
            return deposit
        return None

    def get_by_ids(self, deposit_ids: List[str]) -> Dict[str, Any]:
        """Get multiple deposits by their IDs."""
        if not deposit_ids:
            return {}
        
        # Create a list of DocumentReference objects
        doc_refs = [self.collection.document(did) for did in deposit_ids]
        
        # Fetch documents using firestore_client.get_all
        docs = firestore_client.db.get_all(doc_refs)
        deposits = {}
        for doc in docs:
            if doc.exists:
                deposit = doc.to_dict()
                deposit['id'] = doc.id
                deposits[doc.id] = deposit
        return deposits

    def get_by_type(self, tipo: str):
        """Get depósitos by type (MATERIA_PRIMA, PRODUCAO, ACABADO)."""
        docs = self.collection.where('tipo', '==', tipo).stream()

        deposits = []
        for doc in docs:
            deposit = doc.to_dict()
            deposit['id'] = doc.id
            deposits.append(deposit)

        return deposits

    def create(self, deposit_data):
        """Create a new depósito."""
        # Prepare data
        data = {
            'nome': deposit_data['nome'],
            'tipo': deposit_data.get('tipo', 'MATERIA_PRIMA'),
            'ativo': deposit_data.get('ativo', True),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id

        return data

    def update(self, deposit_id: str, deposit_data):
        """Update an existing depósito."""
        # Get existing depósito
        existing = self.get_by_id(deposit_id)
        if not existing:
            raise ValueError(f"Depósito with ID '{deposit_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow()}

        field_mappings = {
            'nome': 'nome',
            'tipo': 'tipo',
            'ativo': 'ativo'
        }

        for field, key in field_mappings.items():
            if field in deposit_data:
                update_data[key] = deposit_data[field]

        self.collection.document(deposit_id).update(update_data)

        # Return updated depósito
        return self.get_by_id(deposit_id)

    def delete(self, deposit_id: str):
        """Soft delete a depósito by setting ativo to False."""
        existing = self.get_by_id(deposit_id)
        if not existing:
            raise ValueError(f"Depósito with ID '{deposit_id}' not found")

        self.collection.document(deposit_id).update({
            'ativo': False,
            'updated_at': datetime.utcnow()
        })

        return True

    def count(self):
        """Get total count of depósitos."""
        docs = self.collection.stream()
        return len(list(docs))

# Global instance for use throughout the application
deposito_service = DepositoService()
