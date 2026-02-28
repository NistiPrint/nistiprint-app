from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class UomConversionService:
    """Service for managing Unit of Measure conversions for products."""

    def __init__(self):
        self.table = supabase_db.table('conversoes_uom_produto')

    def create_conversion(self, product_id: str, from_unit_id: str, to_unit_id: str, conversion_factor: float):
        """Creates a new UoM conversion rule."""
        if not all([product_id, from_unit_id, to_unit_id, conversion_factor]):
            raise ValueError("All fields are required.")
        if conversion_factor <= 0:
            raise ValueError("Conversion Factor must be positive.")

        data = {
            'produto_id': int(product_id),
            'unidade_origem_id': int(from_unit_id),
            'unidade_destino_id': int(to_unit_id),
            'fator_conversao': float(conversion_factor),
            'created_at': datetime.utcnow().isoformat()
        }

        try:
            response = self.table.insert(data).execute()
            if response.data:
                result = dict(response.data[0])
                result['id'] = str(result.get('id'))
                return result
            return None
        except Exception as e:
            # Log the error and re-raise to be handled by the calling function
            print(f"Error creating conversion: {e}")
            raise

    def get_all_conversions(self):
        """Gets all conversion rules."""
        try:
            response = self.table.select(
                "*, produto:produtos!produto_id(nome), unidade_origem:unidades_medida!unidade_origem_id(nome, abreviacao), unidade_destino:unidades_medida!unidade_destino_id(nome, abreviacao)"
            ).execute()

            conversions = []
            for row in response.data:
                conv = {
                    'id': str(row.get('id')),
                    'productId': row.get('produto_id'),
                    'productName': row.get('produto', {}).get('nome') if row.get('produto') else 'Produto não encontrado',
                    'fromUnitId': row.get('unidade_origem_id'),
                    'toUnitId': row.get('unidade_destino_id'),
                    'conversionFactor': row.get('fator_conversao'),

                    # Flatten joined data
                    'unitName': row.get('unidade_origem', {}).get('nome') if row.get('unidade_origem') else 'N/A', # Backwards compat
                    'fromUnitName': row.get('unidade_origem', {}).get('nome'),
                    'fromUnitSymbol': row.get('unidade_origem', {}).get('abreviacao'),
                    'toUnitName': row.get('unidade_destino', {}).get('nome'),
                    'toUnitSymbol': row.get('unidade_destino', {}).get('abreviacao'),
                }
                conversions.append(conv)

            return conversions
        except Exception as e:
            # Log the error and return an empty list to prevent 500 errors
            print(f"Error getting all conversions: {e}")
            return []

    def get_conversions_for_product(self, product_id: str):
        """Gets all conversion rules for a specific product."""
        try:
            # We need to fetch unit names. Since Supabase join syntax can be tricky if relationships are not perfect,
            # we will fetch the raw data and enrichment will happen if relationship works or we fetch units separately.
            # Assuming relationships 'unidade_origem' and 'unidade_destino' are set up in Supabase (or we rely on IDs for now and enrich in view).
            # Based on schema 'conversoes_uom_produto' has FKs to 'unidades_medida'.

            # Using Supabase syntax for joining: select=*,unidade_origem:unidades_medida!unidade_origem_id(nome),unidade_destino:unidades_medida!unidade_destino_id(nome)
            # Note: The alias syntax might vary. Let's try fetching raw first to avoid 500 if join fails.
            # But to be useful we really need names.

            response = self.table.select(
                "*, unidade_origem:unidades_medida!unidade_origem_id(nome, abreviacao), unidade_destino:unidades_medida!unidade_destino_id(nome, abreviacao)"
            ).eq('produto_id', product_id).execute()

            conversions = []
            for row in response.data:
                conv = {
                    'id': str(row.get('id')),
                    'productId': row.get('produto_id'),
                    'fromUnitId': row.get('unidade_origem_id'),
                    'toUnitId': row.get('unidade_destino_id'),
                    'conversionFactor': row.get('fator_conversao'),

                    # Flatten joined data
                    'unitName': row.get('unidade_origem', {}).get('nome') if row.get('unidade_origem') else 'N/A', # Backwards compat
                    'fromUnitName': row.get('unidade_origem', {}).get('nome'),
                    'fromUnitSymbol': row.get('unidade_origem', {}).get('abreviacao'),
                    'toUnitName': row.get('unidade_destino', {}).get('nome'),
                    'toUnitSymbol': row.get('unidade_destino', {}).get('abreviacao'),
                }
                conversions.append(conv)

            return conversions
        except Exception as e:
            # Log the error and return an empty list to prevent 500 errors
            print(f"Error getting conversions for product {product_id}: {e}")
            return []

    def get_by_id(self, conversion_id: str):
        """Gets a specific conversion rule by its ID."""
        try:
            response = self.table.select(
                 "*, unidade_origem:unidades_medida!unidade_origem_id(nome, abreviacao), unidade_destino:unidades_medida!unidade_destino_id(nome, abreviacao)"
            ).eq('id', conversion_id).execute()

            if response.data:
                row = response.data[0]
                return {
                    'id': str(row.get('id')),
                    'productId': row.get('produto_id'),
                    'fromUnitId': row.get('unidade_origem_id'),
                    'toUnitId': row.get('unidade_destino_id'),
                    'conversionFactor': row.get('fator_conversao'),
                    'unitName': row.get('unidade_origem', {}).get('nome'),
                    'fromUnitName': row.get('unidade_origem', {}).get('nome'),
                    'toUnitName': row.get('unidade_destino', {}).get('nome'),
                }
            return None
        except Exception as e:
            # Log the error and return None to prevent 500 errors
            print(f"Error getting conversion by ID {conversion_id}: {e}")
            return None

    def update_conversion(self, conversion_id: str, from_unit_id: str, to_unit_id: str, conversion_factor: float):
        """Updates an existing UoM conversion rule."""
        if not all([from_unit_id, to_unit_id, conversion_factor]):
            raise ValueError("All fields are required.")
        if conversion_factor <= 0:
            raise ValueError("Conversion Factor must be positive.")

        updates = {
            'unidade_origem_id': int(from_unit_id),
            'unidade_destino_id': int(to_unit_id),
            'fator_conversao': float(conversion_factor),
            'updated_at': datetime.utcnow().isoformat()
        }

        try:
            response = self.table.update(updates).eq('id', conversion_id).execute()
            return self.get_by_id(conversion_id)
        except Exception as e:
            # Log the error and re-raise to be handled by the calling function
            print(f"Error updating conversion {conversion_id}: {e}")
            raise

    def delete_conversion(self, conversion_id: str):
        """Deletes a UoM conversion rule."""
        try:
            response = self.table.delete().eq('id', conversion_id).execute()
            return len(response.data) > 0
        except Exception as e:
            # Log the error and return False to indicate failure
            print(f"Error deleting conversion {conversion_id}: {e}")
            return False

# Global instance
uom_conversion_service = UomConversionService()

