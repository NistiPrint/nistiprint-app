from services.firebase.firestore_client import firestore_client
from datetime import datetime

class ProdutoBlingVinculoService:
    """Service for managing product links with Bling (produto_vinculos_bling) in Firestore."""

    def __init__(self):
        self.collection = firestore_client.collection('produto_vinculos_bling')

    def get_all_by_account(self, conta_bling_id: str):
        """Get all product links by Bling account."""
        docs = self.collection.where('conta_bling_id', '==', conta_bling_id).stream()

        links = []
        for doc in docs:
            link_data = doc.to_dict()
            link_data['id'] = doc.id
            links.append(link_data)

        return links

    def get_by_product_and_account(self, produto_id: str, conta_bling_id: str):
        """Get product link by product and account."""
        docs = self.collection.where('produto_id', '==', produto_id).where('conta_bling_id', '==', conta_bling_id).stream()
        for doc in docs:
            link = doc.to_dict()
            link['id'] = doc.id
            return link
        return None

    def get_by_bling_product(self, conta_bling_id: str, produto_bling_id: int):
        """Get product link by Bling product ID."""
        docs = self.collection.where('conta_bling_id', '==', conta_bling_id).where('produto_bling_id', '==', produto_bling_id).stream()
        for doc in docs:
            link = doc.to_dict()
            link['id'] = doc.id
            return link
        return None

    def get_all(self, conta_bling_id: str = None):
        """Get all product links, optionally filtered by account."""
        query = self.collection

        if conta_bling_id:
            query = query.where('conta_bling_id', '==', conta_bling_id)

        docs = query.order_by('nome_bling').stream()

        links = []
        for doc in docs:
            link_data = doc.to_dict()
            link_data['id'] = doc.id
            links.append(link_data)

        return links

    def create(self, vinculo_data):
        """Create a new product link."""
        # Check if link already exists
        existing = self.get_by_product_and_account(vinculo_data['produto_id'], vinculo_data['conta_bling_id'])
        if existing:
            raise ValueError('Product is already linked to this Bling account')

        # Check if Bling product is already linked
        existing_bling = self.get_by_bling_product(vinculo_data['conta_bling_id'], vinculo_data['produto_bling_id'])
        if existing_bling:
            raise ValueError('Bling product is already linked to another product')

        data = {
            'produto_id': vinculo_data['produto_id'],
            'conta_bling_id': vinculo_data['conta_bling_id'],
            'produto_bling_id': vinculo_data['produto_bling_id'],
            'sku_bling': vinculo_data.get('sku_bling'),
            'nome_bling': vinculo_data.get('nome_bling'),
            'ativo': vinculo_data.get('ativo', True),
            'data_vinculo': datetime.utcnow(),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id

        return data

    def update(self, link_id: str, vinculo_data):
        """Update an existing product link."""
        existing = self.collection.document(link_id).get()
        if not existing.exists:
            raise ValueError('Product link not found')

        update_data = {'updated_at': datetime.utcnow()}

        field_mappings = {
            'sku_bling': 'sku_bling',
            'nome_bling': 'nome_bling',
            'ativo': 'ativo'
        }

        for field, key in field_mappings.items():
            if field in vinculo_data:
                update_data[key] = vinculo_data[field]

        self.collection.document(link_id).update(update_data)

        # Return updated link
        updated = existing.to_dict()
        updated['id'] = link_id
        updated.update(update_data)
        return updated

    def delete(self, link_id: str):
        """Delete a product link."""
        existing = self.collection.document(link_id).get()
        if not existing.exists:
            raise ValueError('Product link not found')

        self.collection.document(link_id).delete()
        return True

    def count_by_account(self, conta_bling_id: str):
        """Get count of product links by account."""
        docs = self.collection.where('conta_bling_id', '==', conta_bling_id).stream()
        return len(list(docs))

# Global instance for use throughout the application
produto_bling_vinculo_service = ProdutoBlingVinculoService()
