import uuid
from services.firebase.firestore_client import firestore_client
from datetime import datetime

class CompositionTemplateService:
    def __init__(self):
        self.collection = firestore_client.collection('composition_templates')


    def get_all_templates(self):
        """Retrieves all composition templates."""
        templates = self.collection.stream()
        result = [self._to_dict(t) for t in templates]
        print(f"DEBUG: get_all_templates returned {len(result)} templates")
        return result

    def get_template_by_id(self, template_id: str):
        """Retrieves a composition template by its ID."""
        template_ref = self.collection.document(template_id)
        template = template_ref.get()
        if not template.exists:
            return None
        
        template_data = self._to_dict(template)
        
        # Fetch items from the subcollection
        items_ref = template_ref.collection('items')
        items = items_ref.stream()
        template_data['items'] = [self._to_dict(item) for item in items]
        
        return template_data

    def create_template(self, name: str, description: str = None, items: list = None):
        """Creates a new composition template."""
        template_id = str(uuid.uuid4())
        new_template_ref = self.collection.document(template_id)
        
        data = {
            'id': template_id,
            'name': name,
            'description': description,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        new_template_ref.set(data)

        if items:
            for item_data in items:
                self.add_item_to_template(template_id, item_data['component_product_id'], item_data['quantity'])

        return self.get_template_by_id(template_id)

    def update_template(self, template_id: str, name: str = None, description: str = None):
        """Updates an existing composition template."""
        template_ref = self.collection.document(template_id)
        if not template_ref.get().exists:
            raise ValueError("Template not found.")

        update_data = {'updated_at': datetime.utcnow()}
        if name:
            update_data['name'] = name
        if description is not None:
            update_data['description'] = description
        
        template_ref.update(update_data)
        return self.get_template_by_id(template_id)

    def delete_template(self, template_id: str):
        """Deletes a composition template and its items."""
        template_ref = self.collection.document(template_id)
        if not template_ref.get().exists:
            raise ValueError("Template not found.")

        # Delete all items in the subcollection first
        items_ref = template_ref.collection('items')
        for item in items_ref.stream():
            item.reference.delete()
            
        template_ref.delete()
        return True

    def add_item_to_template(self, template_id: str, component_product_id: str, quantity: float):
        """Adds or updates an item in a composition template's subcollection."""
        template_ref = self.collection.document(template_id)
        if not template_ref.get().exists:
            raise ValueError("Template not found.")
            
        items_ref = template_ref.collection('items')
        
        # Use component_product_id as the document ID for items to prevent duplicates
        item_ref = items_ref.document(component_product_id)
        
        item_data = {
            'id': component_product_id, # The ID of the item is the product ID itself
            'template_id': template_id,
            'component_product_id': component_product_id,
            'quantity': quantity,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        # Use set with merge=True to create or update
        item_ref.set(item_data, merge=True)
        
        # If it's an update, just modify the quantity and updated_at
        if item_ref.get().exists:
            item_ref.update({
                'quantity': quantity,
                'updated_at': datetime.utcnow()
            })

        return True


    def update_template_item(self, template_id: str, item_id: str, quantity: float):
        """Updates the quantity of an item in a composition template."""
        item_ref = self.collection.document(template_id).collection('items').document(item_id)
        if not item_ref.get().exists:
            raise ValueError("Template item not found.")
        
        item_ref.update({
            'quantity': quantity,
            'updated_at': datetime.utcnow()
        })
        return True

    def delete_template_item(self, template_id: str, item_id: str):
        """Deletes an item from a composition template."""
        item_ref = self.collection.document(template_id).collection('items').document(item_id)
        if not item_ref.get().exists:
            raise ValueError("Template item not found.")
        
        item_ref.delete()
        return True

    def apply_template_to_product(self, template_id: str, product_id: str, overwrite_existing: bool = False):
        """
        Applies a composition template to a product's Bill of Materials (BOM) in Firestore.
        If overwrite_existing is True, existing BOM components for the product are removed first.
        """
        from services.product_service import product_service

        template = self.get_template_by_id(template_id)
        if not template:
            raise ValueError("Template not found.")

        product = product_service.get_by_id(product_id)
        if not product:
            raise ValueError("Product not found.")

        try:
            if overwrite_existing:
                product_service.remove_all_bom_components(product_id)

            for item in template.get('items', []):
                product_service.add_bom_component(
                    product_id, 
                    item['component_product_id'], 
                    item['quantity']
                )
            return True
        except Exception as e:
            # Firestore transactions are handled differently, but for now, we rely on product_service's error handling
            raise e
            
    def _to_dict(self, firestore_obj):
        """Converts a Firestore document snapshot to a dictionary."""
        if not firestore_obj.exists:
            return None
        data = firestore_obj.to_dict()
        data['id'] = firestore_obj.id
        # Convert datetimes to isoformat strings
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

composition_template_service = CompositionTemplateService()
