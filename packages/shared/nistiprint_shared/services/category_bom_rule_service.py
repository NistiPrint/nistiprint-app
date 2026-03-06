from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class CategoryBOMRuleService:
    """Service for managing category BOM rules in Supabase."""

    def __init__(self):
        self.table_name = 'categoria_bom_regras'

    @property
    def table(self):
        return supabase_db.table(self.table_name)

    def get_by_category_pai(self, categoria_pai_id):
        """Get all rules for a parent category."""
        response = self.table.select("*, categoria_componente:categorias!categoria_componente_id(nome)").eq('categoria_pai_id', categoria_pai_id).order('ordem').execute()
        rules = []
        for row in response.data:
            rule = dict(row)
            # Flatten join data
            if 'categoria_componente' in rule and rule['categoria_componente']:
                rule['categoria_componente_nome'] = rule['categoria_componente'].get('nome')
            rules.append(rule)
        return rules

    def create(self, rule_data):
        """Create a new category BOM rule."""
        data = {
            'categoria_pai_id': rule_data['categoria_pai_id'],
            'nome_grupo': rule_data['nome_grupo'],
            'categoria_componente_id': rule_data['categoria_componente_id'],
            'min_quantidade': rule_data.get('min_quantidade', 1),
            'max_quantidade': rule_data.get('max_quantidade', 1),
            'ordem': rule_data.get('ordem', 0),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = self.table.insert(data).execute()
        if response.data:
            return response.data[0]
        return None

    def update(self, rule_id, rule_data):
        """Update an existing rule."""
        data = {
            'updated_at': datetime.utcnow().isoformat()
        }
        
        fields = ['nome_grupo', 'categoria_componente_id', 'min_quantidade', 'max_quantidade', 'ordem']
        for field in fields:
            if field in rule_data:
                data[field] = rule_data[field]

        response = self.table.update(data).eq('id', rule_id).execute()
        if response.data:
            return response.data[0]
        return None

    def delete(self, rule_id):
        """Delete a rule."""
        response = self.table.delete().eq('id', rule_id).execute()
        return len(response.data) > 0

    def delete_by_category_pai(self, categoria_pai_id):
        """Delete all rules for a parent category."""
        response = self.table.delete().eq('categoria_pai_id', categoria_pai_id).execute()
        return len(response.data) > 0

category_bom_rule_service = CategoryBOMRuleService()

