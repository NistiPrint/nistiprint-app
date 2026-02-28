from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class PontoColetaService:
    """Service for managing collection points (pontos de coleta) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('pontos_coleta')
        return self._table

    def get_all(self, active_only=True):
        """Get all collection points ordered by name."""
        try:
            query = self.table.select("*")
            if active_only:
                query = query.eq('ativo', True)
            
            response = query.order("nome", desc=False).execute()
            return response.data
        except Exception as e:
            print(f"Error in PontoColetaService.get_all: {e}")
            return []

    def get_by_id(self, id: int):
        """Get collection point by ID."""
        try:
            response = self.table.select("*").eq('id', id).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error in PontoColetaService.get_by_id: {e}")
            return None

    def create(self, data):
        """Create a new collection point."""
        payload = {
            'nome': data['nome'],
            'horario_corte_padrao': data['horario_corte_padrao'],
            'endereco': data.get('endereco'),
            'ativo': data.get('ativo', True),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = self.table.insert(payload).execute()
        if response.data:
            return response.data[0]
        return None

    def update(self, id: int, data):
        """Update an existing collection point."""
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        fields = ['nome', 'horario_corte_padrao', 'endereco', 'ativo']
        for field in fields:
            if field in data:
                update_data[field] = data[field]

        response = self.table.update(update_data).eq('id', id).execute()
        if response.data:
            return response.data[0]
        return None

    def delete(self, id: int):
        """Soft delete a collection point by setting ativo to False."""
        self.table.update({
            'ativo': False,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', id).execute()
        return True

# Global instance
ponto_coleta_service = PontoColetaService()

