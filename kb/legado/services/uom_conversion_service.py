from services.firebase.firestore_client import firestore_client
from datetime import datetime

class UomConversionService:
    """Service for managing Unit of Measure conversions for products."""

    def __init__(self):
        self.collection = firestore_client.collection('product_uom_conversions')

    def create_conversion(self, product_id: str, unit_name: str, conversion_factor: float):
        """Creates a new UoM conversion rule."""
        if not all([product_id, unit_name, conversion_factor]):
            raise ValueError("Product ID, Unit Name, and Conversion Factor are required.")
        if conversion_factor <= 0:
            raise ValueError("Conversion Factor must be positive.")

        doc_ref = self.collection.document()
        data = {
            'id': doc_ref.id,
            'productId': product_id,
            'unitName': unit_name,
            'conversionFactor': conversion_factor,
            'createdAt': datetime.utcnow()
        }
        doc_ref.set(data)
        return data

    def get_conversions_for_product(self, product_id: str):
        """Gets all conversion rules for a specific product."""
        docs = self.collection.where('productId', '==', product_id).stream()
        return [doc.to_dict() for doc in docs]

    def get_by_id(self, conversion_id: str):
        """Gets a specific conversion rule by its ID."""
        doc = self.collection.document(conversion_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def update_conversion(self, conversion_id: str, unit_name: str, conversion_factor: float):
        """Updates an existing UoM conversion rule."""
        if not all([unit_name, conversion_factor]):
            raise ValueError("Unit Name and Conversion Factor are required.")
        if conversion_factor <= 0:
            raise ValueError("Conversion Factor must be positive.")

        doc_ref = self.collection.document(conversion_id)
        updates = {
            'unitName': unit_name,
            'conversionFactor': conversion_factor,
            'updatedAt': datetime.utcnow()
        }
        doc_ref.update(updates)
        return self.get_by_id(conversion_id)

    def delete_conversion(self, conversion_id: str):
        """Deletes a UoM conversion rule."""
        self.collection.document(conversion_id).delete()
        return True

# Global instance
uom_conversion_service = UomConversionService()
