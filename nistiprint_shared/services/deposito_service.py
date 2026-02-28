from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
from typing import List, Dict, Any

class DepositoService:
    """Service for managing warehouses/depots (depósitos) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('depositos')
        return self._table

    def get_all(self):
        """Get all depósitos ordered by name."""
        query = self.table.select("*").order("nome", desc=False)
        response = supabase_db.execute_with_retry(query)

        deposits = []
        for row in response.data:
            deposit = dict(row)
            deposit['id'] = row.get('id')
            deposit['name'] = row.get('nome')
            deposits.append(deposit)

        return deposits

    def get_by_id(self, deposit_id: str):
        """Get depósito by ID."""
        query = self.table.select("*").eq('id', deposit_id)
        response = supabase_db.execute_with_retry(query)
        if response.data:
            deposit = dict(response.data[0])
            deposit['id'] = deposit.get('id')
            deposit['name'] = deposit.get('nome')
            return deposit
        return None

    def get_by_ids(self, deposit_ids: List[str]) -> Dict[str, Any]:
        """Get multiple deposits by their IDs."""
        if not deposit_ids:
            return {}

        query = self.table.select("*").in_('id', deposit_ids)
        response = supabase_db.execute_with_retry(query)
        deposits = {}
        for row in response.data:
            deposit = dict(row)
            deposit['id'] = row.get('id')
            deposits[deposit['id']] = deposit
        return deposits

    def get_by_type(self, tipo: str):
        """Get depósitos by type (MATERIA_PRIMA, PRODUCAO, ACABADO)."""
        query = self.table.select("*").eq('tipo', tipo)
        response = supabase_db.execute_with_retry(query)

        deposits = []
        for row in response.data:
            deposit = dict(row)
            deposit['id'] = row.get('id')
            deposits.append(deposit)

        return deposits

    def get_default(self):
        """Get the default depósito."""
        query = self.table.select("*").eq('is_default', True)
        response = supabase_db.execute_with_retry(query)
        if response.data:
            deposit = dict(response.data[0])
            deposit['id'] = deposit.get('id')
            deposit['name'] = deposit.get('nome')
            return deposit
        return None

    def _unset_other_defaults(self, exclude_id: str = None):
        """Internal helper to unset is_default for all other deposits."""
        query = self.table.update({'is_default': False}).eq('is_default', True)
        if exclude_id:
            query = query.neq('id', exclude_id)
        supabase_db.execute_with_retry(query)

    def create(self, deposit_data):
        """Create a new depósito."""
        # Handle default logic
        if deposit_data.get('is_default'):
            self._unset_other_defaults()

        # Prepare data
        data = {
            'nome': deposit_data['nome'],
            'tipo': deposit_data.get('tipo', 'MATERIA_PRIMA'),
            'ativo': deposit_data.get('ativo', True),
            'is_default': deposit_data.get('is_default', False),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        query = self.table.insert(data)
        response = supabase_db.execute_with_retry(query)
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            return result

        return None

    def update(self, deposit_id: str, deposit_data):
        """Update an existing depósito."""
        # Get existing depósito
        existing = self.get_by_id(deposit_id)
        if not existing:
            raise ValueError(f"Depósito with ID '{deposit_id}' not found")

        # Handle default logic
        if deposit_data.get('is_default'):
             self._unset_other_defaults(exclude_id=deposit_id)

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        field_mappings = {
            'nome': 'nome',
            'tipo': 'tipo',
            'ativo': 'ativo',
            'is_default': 'is_default'
        }

        for field, key in field_mappings.items():
            if field in deposit_data:
                update_data[key] = deposit_data[field]

        query = self.table.update(update_data).eq('id', deposit_id)
        response = supabase_db.execute_with_retry(query)

        # Return updated depósito
        return self.get_by_id(deposit_id)

    def delete(self, deposit_id: str):
        """Soft delete a depósito by setting ativo to False."""
        existing = self.get_by_id(deposit_id)
        if not existing:
            raise ValueError(f"Depósito with ID '{deposit_id}' not found")

        query = self.table.update({
            'ativo': False,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', deposit_id)
        response = supabase_db.execute_with_retry(query)

        return len(response.data) > 0

    def count(self):
        """Get total count of depósitos."""
        query = self.table.select("count", count="exact")
        response = supabase_db.execute_with_retry(query)
        return response.count if response.count is not None else 0

# Global instance for use throughout the application
deposito_service = DepositoService()

