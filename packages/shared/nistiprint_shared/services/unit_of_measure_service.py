from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

class UnitOfMeasureService:
    """Service for managing units of measure in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('unidades_medida')
        return self._table

    def _execute_query(self, query):
        """Execute query with retry logic for connection errors."""
        return supabase_db.execute_with_retry(query)

    def get_all(self):
        """Get all units of measure."""
        try:
            query = self.table.select("*").order("nome", desc=False)
            response = self._execute_query(query)
            units = []
            for row in response.data:
                unit = dict(row)
                unit['name'] = row.get('nome')
                unit['symbol'] = row.get('abreviacao')
                units.append(unit)
            return units
        except Exception as e:
            logging.error(f"Error fetching units of measure: {e}")
            raise

    def get_by_id(self, unit_id: str):
        """Get unit of measure by ID."""
        try:
            query = self.table.select("*").eq('id', unit_id)
            response = self._execute_query(query)
            if response.data:
                row = response.data[0]
                unit = dict(row)
                unit['name'] = row.get('nome')
                unit['symbol'] = row.get('abreviacao')
                return unit
            return None
        except Exception as e:
            logging.error(f"Error fetching unit of measure by ID {unit_id}: {e}")
            raise

    def get_by_name(self, name: str):
        """Get unit of measure by name."""
        try:
            query = self.table.select("*").eq('nome', name)
            response = self._execute_query(query)
            if response.data:
                row = response.data[0]
                unit = dict(row)
                unit['name'] = row.get('nome')
                unit['symbol'] = row.get('abreviacao')
                return unit
            return None
        except Exception as e:
            logging.error(f"Error fetching unit of measure by name '{name}': {e}")
            raise

    def get_by_symbol(self, symbol: str):
        """Get unit of measure by symbol."""
        try:
            query = self.table.select("*").eq('abreviacao', symbol)
            response = self._execute_query(query)
            if response.data:
                row = response.data[0]
                unit = dict(row)
                unit['name'] = row.get('nome')
                unit['symbol'] = row.get('abreviacao')
                return unit
            return None
        except Exception as e:
            logging.error(f"Error fetching unit of measure by symbol '{symbol}': {e}")
            raise

    def create(self, unit_data):
        """Create a new unit of measure."""
        try:
            # Check if name already exists
            if self.get_by_name(unit_data['name']):
                raise ValueError(f"Unit of measure with name '{unit_data['name']}' already exists")

            # Check if symbol already exists
            if self.get_by_symbol(unit_data['symbol']):
                raise ValueError(f"Unit of measure with symbol '{unit_data['symbol']}' already exists")

            data = {
                'nome': unit_data['name'],
                'abreviacao': unit_data['symbol']
            }

            query = self.table.insert(data)
            response = self._execute_query(query)
            if response.data:
                row = response.data[0]
                result = dict(row)
                result['name'] = row.get('nome')
                result['symbol'] = row.get('abreviacao')
                return result
            return None
        except ValueError:
            raise
        except Exception as e:
            logging.error(f"Error creating unit of measure: {e}")
            raise

    def update(self, unit_id: str, unit_data):
        """Update an existing unit of measure."""
        try:
            # Check if name is being updated and if it conflicts
            if 'name' in unit_data:
                existing_name = self.get_by_name(unit_data['name'])
                # Note: IDs in Supabase are usually integers, need consistent comparison (str vs int)
                # Assuming unit_id passed is string, but DB ID is int.
                if existing_name and str(existing_name['id']) != str(unit_id):
                    raise ValueError(f"Unit of measure with name '{unit_data['name']}' already exists")

            # Check if symbol is being updated and if it conflicts
            if 'symbol' in unit_data:
                existing_symbol = self.get_by_symbol(unit_data['symbol'])
                if existing_symbol and str(existing_symbol['id']) != str(unit_id):
                    raise ValueError(f"Unit of measure with symbol '{unit_data['symbol']}' already exists")

            data = {}
            if 'name' in unit_data:
                data['nome'] = unit_data['name']
            if 'symbol' in unit_data:
                data['abreviacao'] = unit_data['symbol']

            if data:  # Only update if there's data to update
                query = self.table.update(data).eq('id', unit_id)
                self._execute_query(query)

            # Return updated unit
            return self.get_by_id(unit_id)
        except ValueError:
            raise
        except Exception as e:
            logging.error(f"Error updating unit of measure {unit_id}: {e}")
            raise

    def delete(self, unit_id: str):
        """Delete a unit of measure."""
        try:
            query = self.table.delete().eq('id', unit_id)
            self._execute_query(query)
            return True
        except Exception as e:
            logging.error(f"Error deleting unit of measure {unit_id}: {e}")
            raise

# Global instance for use throughout the application
unit_of_measure_service = UnitOfMeasureService()

