from firebase_admin import firestore
from services.firebase.firestore_client import firestore_client
from datetime import datetime

class CategoryService:
    """Service for managing categories in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('categories')
        return self._collection

    def get_all(self):
        """Get all categories."""
        docs = self.collection.order_by('name').stream()
        categories = []
        for doc in docs:
            category = doc.to_dict()
            category['id'] = doc.id
            categories.append(category)
        return categories

    def get_by_id(self, category_id: str):
        """Get category by ID."""
        doc = self.collection.document(category_id).get()
        if doc.exists:
            category = doc.to_dict()
            category['id'] = doc.id
            return category
        return None

    def get_by_bling_id(self, bling_category_id: int):
        """Get category by Bling category ID."""
        docs = self.collection.where(field='bling_category_id', op='==', value=bling_category_id).stream()
        for doc in docs:
            category = doc.to_dict()
            category['id'] = doc.id
            return category
        return None

    def get_children(self, parent_category_id: str):
        """Get child categories of a parent category."""
        docs = self.collection.where('parent_category_id', '==', parent_category_id).order_by('name').stream()
        children = []
        for doc in docs:
            category = doc.to_dict()
            category['id'] = doc.id
            children.append(category)
        return children

    def get_root_categories(self):
        """Get root categories (those without a parent)."""
        docs = self.collection.where('parent_category_id', '==', None).order_by('name').stream()
        categories = []
        for doc in docs:
            category = doc.to_dict()
            category['id'] = doc.id
            categories.append(category)
        return categories

    def create(self, category_data):
        """Create a new category."""
        data = {
            'name': category_data['name'],
            'description': category_data.get('description'),
            'bling_category_id': category_data.get('bling_category_id'),
            'parent_category_id': category_data.get('parent_category_id'),
            'composition_template_id': category_data.get('composition_template_id'),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id
        return data

    def update(self, category_id: str, category_data):
        """Update an existing category."""
        data = {
            'updated_at': datetime.utcnow()
        }

        if 'name' in category_data:
            data['name'] = category_data['name']
        if 'description' in category_data:
            data['description'] = category_data['description']
        if 'bling_category_id' in category_data:
            data['bling_category_id'] = category_data['bling_category_id']
        if 'parent_category_id' in category_data:
            data['parent_category_id'] = category_data['parent_category_id']
        if 'composition_template_id' in category_data:
            data['composition_template_id'] = category_data['composition_template_id']

        self.collection.document(category_id).update(data)

        # Return updated category
        updated = self.get_by_id(category_id)
        return updated

    def delete(self, category_id: str):
        """Delete a category."""
        self.collection.document(category_id).delete()
        return True

# Global instance for use throughout the application
category_service = CategoryService()
