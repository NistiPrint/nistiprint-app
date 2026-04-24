from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client
from datetime import datetime

class TagService:
    """Service for managing tags in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('tags')
        return self._collection

    def get_all(self):
        """Get all tags."""
        docs = self.collection.order_by('name').stream()
        tags = []
        for doc in docs:
            tag = doc.to_dict()
            tag['id'] = doc.id
            tags.append(tag)
        return tags

    def get_by_id(self, tag_id: str):
        """Get tag by ID."""
        doc = self.collection.document(tag_id).get()
        if doc.exists:
            tag = doc.to_dict()
            tag['id'] = doc.id
            return tag
        return None

    def get_by_name(self, name: str):
        """Get tag by name."""
        docs = self.collection.where('name', '==', name).stream()
        for doc in docs:
            tag = doc.to_dict()
            tag['id'] = doc.id
            return tag
        return None

    def get_products_count(self, tag_id: str):
        """Get the count of products associated with this tag."""
        # This is a basic count - in a real implementation, you might want to cache this
        # or use Firestore's aggregation features if available
        # For now, we'll just return the number of products in the products array
        tag = self.get_by_id(tag_id)
        if tag and 'products' in tag:
            return len(tag['products'])
        return 0

    def create(self, tag_data):
        """Create a new tag."""
        # Check if tag with same name already exists
        if self.get_by_name(tag_data['name']):
            raise ValueError(f"Tag with name '{tag_data['name']}' already exists")

        data = {
            'name': tag_data['name'],
            'composition_template_id': tag_data.get('composition_template_id'),
            'created_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id
        return data

    def update(self, tag_id: str, tag_data):
        """Update an existing tag."""
        # Check if name is being updated and if it conflicts
        if 'name' in tag_data:
            existing = self.get_by_name(tag_data['name'])
            if existing and existing['id'] != tag_id:
                raise ValueError(f"Tag with name '{tag_data['name']}' already exists")

        data = {}
        if 'name' in tag_data:
            data['name'] = tag_data['name']
        if 'composition_template_id' in tag_data:
            data['composition_template_id'] = tag_data['composition_template_id']

        if data:  # Only update if there's data to update
            self.collection.document(tag_id).update(data)

        # Return updated tag
        updated = self.get_by_id(tag_id)
        return updated

    def delete(self, tag_id: str):
        """Delete a tag."""
        # Check if tag is being used by products
        tag = self.get_by_id(tag_id)
        if tag and 'products' in tag and len(tag['products']) > 0:
            raise ValueError("Cannot delete tag that is associated with products")

        self.collection.document(tag_id).delete()
        return True

# Global instance for use throughout the application
tag_service = TagService()
