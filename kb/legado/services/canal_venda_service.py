from services.firebase.firestore_client import firestore_client
from datetime import datetime

class CanalVendaService:
    """Service for managing sales channels (canais de venda) in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('canais_venda')
        return self._collection

    def get_all(self):
        """Get all sales channels ordered by name."""
        docs = self.collection.order_by('nome').stream()

        channels = []
        for doc in docs:
            channel_data = doc.to_dict()
            channel_data['id'] = doc.id
            channels.append(channel_data)

        return channels

    def get_by_id(self, channel_id: str):
        """Get sales channel by ID."""
        doc = self.collection.document(channel_id).get()
        if doc.exists:
            channel = doc.to_dict()
            channel['id'] = doc.id
            return channel
        return None

    def get_by_platform(self, plataforma: str):
        """Get sales channels by platform."""
        docs = self.collection.where(field='plataforma', op='==', value=plataforma).stream()

        channels = []
        for doc in docs:
            channel = doc.to_dict()
            channel['id'] = doc.id
            channels.append(channel)

        return channels

    def get_by_bling_account(self, conta_bling_id: str):
        """Get sales channels by Bling account."""
        docs = self.collection.where(field='conta_bling_id', op='==', value=conta_bling_id).stream()

        channels = []
        for doc in docs:
            channel = doc.to_dict()
            channel['id'] = doc.id
            channels.append(channel)

        return channels

    def create(self, channel_data):
        """Create a new sales channel."""
        # Prepare data
        data = {
            'nome': channel_data['nome'],
            'plataforma': channel_data.get('plataforma'),
            'conta_bling_id': channel_data['conta_bling_id'],
            'ativo': channel_data.get('ativo', True),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id

        return data

    def update(self, channel_id: str, channel_data):
        """Update an existing sales channel."""
        # Get existing channel
        existing = self.get_by_id(channel_id)
        if not existing:
            raise ValueError(f"Sales channel with ID '{channel_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow()}

        field_mappings = {
            'nome': 'nome',
            'plataforma': 'plataforma',
            'conta_bling_id': 'conta_bling_id',
            'ativo': 'ativo'
        }

        for field, key in field_mappings.items():
            if field in channel_data:
                update_data[key] = channel_data[field]

        self.collection.document(channel_id).update(update_data)

        # Return updated channel
        return self.get_by_id(channel_id)

    def delete(self, channel_id: str):
        """Soft delete a sales channel by setting ativo to False."""
        existing = self.get_by_id(channel_id)
        if not existing:
            raise ValueError(f"Sales channel with ID '{channel_id}' not found")

        self.collection.document(channel_id).update({
            'ativo': False,
            'updated_at': datetime.utcnow()
        })

        return True

    def count(self):
        """Get total count of sales channels."""
        docs = self.collection.where(field='ativo', op='==', value=True).stream()
        return len(list(docs))

# Global instance for use throughout the application
canal_venda_service = CanalVendaService()
