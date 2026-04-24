from services.firebase.firestore_client import firestore_client

class UnitOfMeasureService:
    """Service for managing units of measure in Firestore."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        """Lazy initialization of collection."""
        if self._collection is None:
            self._collection = firestore_client.collection('units_of_measure')
        return self._collection

    def get_all(self):
        """Get all units of measure."""
        docs = self.collection.order_by('name').stream()
        units = []
        for doc in docs:
            unit = doc.to_dict()
            unit['id'] = doc.id
            units.append(unit)
        return units

    def get_by_id(self, unit_id: str):
        """Get unit of measure by ID."""
        doc = self.collection.document(unit_id).get()
        if doc.exists:
            unit = doc.to_dict()
            unit['id'] = doc.id
            return unit
        return None

    def get_by_name(self, name: str):
        """Get unit of measure by name."""
        docs = self.collection.where('name', '==', name).stream()
        for doc in docs:
            unit = doc.to_dict()
            unit['id'] = doc.id
            return unit
        return None

    def get_by_symbol(self, symbol: str):
        """Get unit of measure by symbol."""
        docs = self.collection.where('symbol', '==', symbol).stream()
        for doc in docs:
            unit = doc.to_dict()
            unit['id'] = doc.id
            return unit
        return None

    def create(self, unit_data):
        """Create a new unit of measure."""
        # Check if name already exists
        if self.get_by_name(unit_data['name']):
            raise ValueError(f"Unit of measure with name '{unit_data['name']}' already exists")

        # Check if symbol already exists
        if self.get_by_symbol(unit_data['symbol']):
            raise ValueError(f"Unit of measure with symbol '{unit_data['symbol']}' already exists")

        data = {
            'name': unit_data['name'],
            'symbol': unit_data['symbol']
        }

        doc_ref = self.collection.add(data)[1]
        data['id'] = doc_ref.id
        return data

    def update(self, unit_id: str, unit_data):
        """Update an existing unit of measure."""
        # Check if name is being updated and if it conflicts
        if 'name' in unit_data:
            existing_name = self.get_by_name(unit_data['name'])
            if existing_name and existing_name['id'] != unit_id:
                raise ValueError(f"Unit of measure with name '{unit_data['name']}' already exists")

        # Check if symbol is being updated and if it conflicts
        if 'symbol' in unit_data:
            existing_symbol = self.get_by_symbol(unit_data['symbol'])
            if existing_symbol and existing_symbol['id'] != unit_id:
                raise ValueError(f"Unit of measure with symbol '{unit_data['symbol']}' already exists")

        data = {}
        if 'name' in unit_data:
            data['name'] = unit_data['name']
        if 'symbol' in unit_data:
            data['symbol'] = unit_data['symbol']

        if data:  # Only update if there's data to update
            self.collection.document(unit_id).update(data)

        # Return updated unit
        updated = self.get_by_id(unit_id)
        return updated

    def delete(self, unit_id: str):
        """Delete a unit of measure."""
        self.collection.document(unit_id).delete()
        return True

# Global instance for use throughout the application
unit_of_measure_service = UnitOfMeasureService()
