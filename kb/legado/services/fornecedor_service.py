from services.firebase.firestore_client import firestore_client
from datetime import datetime

class FornecedorService:
    """Service for managing suppliers (fornecedores) in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('fornecedores')
        return self._collection

    def get_all(self, page: int = 1, per_page: int = 50):
        """Get all suppliers with pagination."""
        docs = self.collection.order_by('nome_razao_social').stream()

        suppliers = []
        skip = (page - 1) * per_page
        limit = skip + per_page

        for i, doc in enumerate(docs):
            if i < skip:
                continue
            if i >= limit and limit != skip:
                break

            supplier_data = doc.to_dict()
            supplier_data['id'] = doc.id
            suppliers.append(supplier_data)

        return suppliers

    def get_by_id(self, supplier_id: str):
        """Get supplier by ID."""
        doc = self.collection.document(supplier_id).get()
        if doc.exists:
            supplier = doc.to_dict()
            supplier['id'] = doc.id
            return supplier
        return None

    def search(self, query: str):
        """Search suppliers by name or document."""
        # Simple search implementation
        docs = self.collection.stream()
        results = []

        for doc in docs:
            supplier = doc.to_dict()
            supplier['id'] = doc.id

            name = supplier.get('nome_razao_social', '').lower()
            doc_value = supplier.get('cpf_cnpj', '').lower()

            if query.lower() in name or query.lower() in doc_value:
                results.append(supplier)

        return results

    def create(self, supplier_data):
        """Create a new supplier."""
        # Check document uniqueness if provided
        if supplier_data.get('cpf_cnpj'):
            existing = self.get_by_document(supplier_data['cpf_cnpj'])
            if existing:
                raise ValueError(f"Supplier with document '{supplier_data['cpf_cnpj']}' already exists")

        # Prepare data
        data = {
            'nome_razao_social': supplier_data['nome_razao_social'],
            'cpf_cnpj': supplier_data.get('cpf_cnpj'),
            'email': supplier_data.get('email'),
            'telefone': supplier_data.get('telefone'),
            'ativo': supplier_data.get('ativo', True),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id

        return data

    def update(self, supplier_id: str, supplier_data):
        """Update an existing supplier."""
        # Check document uniqueness if being updated
        if 'cpf_cnpj' in supplier_data:
            existing = self.get_by_document(supplier_data['cpf_cnpj'])
            if existing and existing['id'] != supplier_id:
                raise ValueError(f"Supplier with document '{supplier_data['cpf_cnpj']}' already exists")

        # Get existing supplier
        existing = self.get_by_id(supplier_id)
        if not existing:
            raise ValueError(f"Supplier with ID '{supplier_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow()}

        field_mappings = {
            'nome_razao_social': 'nome_razao_social',
            'cpf_cnpj': 'cpf_cnpj',
            'email': 'email',
            'telefone': 'telefone',
            'ativo': 'ativo'
        }

        for field, key in field_mappings.items():
            if field in supplier_data:
                update_data[key] = supplier_data[field]

        self.collection.document(supplier_id).update(update_data)

        # Return updated supplier
        return self.get_by_id(supplier_id)

    def delete(self, supplier_id: str):
        """Soft delete a supplier by setting ativo to False."""
        existing = self.get_by_id(supplier_id)
        if not existing:
            raise ValueError(f"Supplier with ID '{supplier_id}' not found")

        self.collection.document(supplier_id).update({
            'ativo': False,
            'updated_at': datetime.utcnow()
        })

        return True

    def get_by_document(self, cpf_cnpj: str):
        """Get supplier by CPF/CNPJ."""
        docs = self.collection.where('cpf_cnpj', '==', cpf_cnpj).stream()
        for doc in docs:
            supplier = doc.to_dict()
            supplier['id'] = doc.id
            return supplier
        return None

    def count(self):
        """Get total count of suppliers."""
        docs = self.collection.stream()
        return len(list(docs))

# Global instance for use throughout the application
fornecedor_service = FornecedorService()
