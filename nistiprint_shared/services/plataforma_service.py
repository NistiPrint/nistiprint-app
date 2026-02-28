from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class PlataformaService:
    """Service for managing platforms (plataformas) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('plataformas')
        return self._table

    def get_all(self):
        """Get all platforms ordered by name."""
        response = self.table.select("*").order("nome", desc=False).execute()

        plataformas = []
        for row in response.data:
            p_data = dict(row)
            p_data['id'] = row.get('id')
            # Map 'ativa' (DB) to 'ativo' (App) if 'ativo' is missing
            if 'ativo' not in p_data and 'ativa' in p_data:
                p_data['ativo'] = p_data['ativa']
            plataformas.append(p_data)

        return plataformas

    def get_by_id(self, plataforma_id: str):
        """Get platform by ID."""
        response = self.table.select("*").eq('id', plataforma_id).execute()
        if response.data:
            p_data = dict(response.data[0])
            p_data['id'] = p_data.get('id')
            # Map 'ativa' (DB) to 'ativo' (App)
            if 'ativo' not in p_data and 'ativa' in p_data:
                p_data['ativo'] = p_data['ativa']
            return p_data
        return None

    def create(self, plataforma_data):
        """Create a new platform."""
        # Prepare data
        # Map 'ativo' (App) to 'ativa' (DB)
        ativo_status = plataforma_data.get('ativo', True)
        
        data = {
            'nome': plataforma_data['nome'],
            'ativa': ativo_status,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            if 'ativo' not in result and 'ativa' in result:
                result['ativo'] = result['ativa']
            return result

        return None

    def update(self, plataforma_id: str, plataforma_data):
        """Update an existing platform."""
        existing = self.get_by_id(plataforma_id)
        if not existing:
            raise ValueError(f"Platform with ID '{plataforma_id}' not found")

        update_data = {'updated_at': datetime.utcnow().isoformat()}

        if 'nome' in plataforma_data:
            update_data['nome'] = plataforma_data['nome']
        if 'ativo' in plataforma_data:
            update_data['ativa'] = plataforma_data['ativo']

        response = self.table.update(update_data).eq('id', plataforma_id).execute()
        
        # Return updated platform
        return self.get_by_id(plataforma_id)

    def delete(self, plataforma_id: str):
        """Delete a platform."""
        self.table.delete().eq('id', plataforma_id).execute()
        return True

# Global instance
plataforma_service = PlataformaService()

