from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class RegraLogisticaService:
    """Service for managing structured logistics rules in Supabase using basic CRUD operations."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('regras_logisticas_canal')
        return self._table

    def get_by_canal(self, canal_venda_id: int):
        """Get all logistics rules for a specific channel."""
        try:
            response = self.table.select("*, pontos_coleta(nome)").eq('canal_venda_id', canal_venda_id).order('prioridade_uso').execute()

            # Formatar para o frontend (agrupar por modalidade)
            regras_por_modalidade = {}
            for row in response.data:
                modalidade = row['modalidade']
                if modalidade not in regras_por_modalidade:
                    regras_por_modalidade[modalidade] = []

                # Enriquecer com nome do ponto
                if row.get('pontos_coleta'):
                    row['ponto_coleta_nome'] = row['pontos_coleta'].get('nome')

                # Adicionar alias 'tipo' para compatibilidade com o frontend
                row['tipo'] = row['tipo_envio']

                regras_por_modalidade[modalidade].append(row)

            return regras_por_modalidade
        except Exception as e:
            print(f"Error in RegraLogisticaService.get_by_canal: {e}")
            return {}

    def create_regra(self, regra_data):
        """Create a single logistics rule."""
        try:
            payload = {
                'canal_venda_id': regra_data['canal_venda_id'],
                'modalidade': regra_data['modalidade'],
                'tipo_envio': regra_data['tipo_envio'],
                'horario_limite': regra_data['horario_limite'],
                'ponto_coleta_id': regra_data.get('ponto_coleta_id'),
                'prioridade_uso': regra_data.get('prioridade_uso', 1),
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }

            response = self.table.insert(payload).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error in RegraLogisticaService.create_regra: {e}")
            raise e

    def update_regra(self, regra_id: int, regra_data):
        """Update a single logistics rule."""
        try:
            payload = {
                'modalidade': regra_data['modalidade'],
                'tipo_envio': regra_data['tipo_envio'],
                'horario_limite': regra_data['horario_limite'],
                'ponto_coleta_id': regra_data.get('ponto_coleta_id'),
                'prioridade_uso': regra_data.get('prioridade_uso'),
                'updated_at': datetime.utcnow().isoformat()
            }

            response = self.table.update(payload).eq('id', regra_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error in RegraLogisticaService.update_regra: {e}")
            raise e

    def delete_regra(self, regra_id: int):
        """Delete a single logistics rule."""
        try:
            response = self.table.delete().eq('id', regra_id).execute()
            return len(response.data) > 0
        except Exception as e:
            print(f"Error in RegraLogisticaService.delete_regra: {e}")
            raise e

    def delete_all_by_canal(self, canal_venda_id: int):
        """Delete all logistics rules for a specific channel."""
        try:
            response = self.table.delete().eq('canal_venda_id', canal_venda_id).execute()
            return True
        except Exception as e:
            print(f"Error in RegraLogisticaService.delete_all_by_canal: {e}")
            raise e

    def bulk_create_regras(self, regras_data):
        """Create multiple logistics rules at once."""
        try:
            if not regras_data:
                return []

            payload = []
            for regra in regras_data:
                item = {
                    'canal_venda_id': regra['canal_venda_id'],
                    'modalidade': regra['modalidade'],
                    'tipo_envio': regra['tipo_envio'],
                    'horario_limite': regra['horario_limite'],
                    'ponto_coleta_id': regra.get('ponto_coleta_id'),
                    'prioridade_uso': regra.get('prioridade_uso', 1),
                    'created_at': datetime.utcnow().isoformat(),
                    'updated_at': datetime.utcnow().isoformat()
                }
                payload.append(item)

            response = self.table.insert(payload).execute()
            return response.data
        except Exception as e:
            print(f"Error in RegraLogisticaService.bulk_create_regras: {e}")
            raise e

# Global instance
regra_logistica_service = RegraLogisticaService()

