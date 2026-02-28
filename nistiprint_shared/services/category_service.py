from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class CategoryService:
    """Service for managing categories in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('categorias')
        return self._table

    def get_all(self):
        """Get all categories."""
        query = self.table.select("*").order("nome", desc=False)
        response = supabase_db.execute_with_retry(query)
        categories = []
        for row in response.data:
            category = dict(row)
            category['name'] = row.get('nome')
            categories.append(category)
        return categories

    def get_by_id(self, category_id: str):
        """Get category by ID."""
        query = self.table.select("*").eq('id', category_id)
        response = supabase_db.execute_with_retry(query)
        if response.data:
            category = dict(response.data[0])
            category['name'] = category.get('nome')
            return category
        return None

    def get_marketable_ids(self):
        """Get IDs of categories marked as marketable."""
        query = self.table.select("id").eq("comercializavel", True)
        response = supabase_db.execute_with_retry(query)
        return [row['id'] for row in response.data] if response.data else []

    def get_children(self, parent_category_id: str):
        """Get child categories of a parent category."""
        query = self.table.select("*").eq('categoria_pai_id', parent_category_id).order("nome", desc=False)
        response = supabase_db.execute_with_retry(query)
        children = []
        for row in response.data:
            category = dict(row)
            children.append(category)
        return children

    def get_root_categories(self):
        """Get root categories (those without a parent)."""
        query = self.table.select("*").is_('categoria_pai_id', None).order("nome", desc=False)
        response = supabase_db.execute_with_retry(query)
        categories = []
        for row in response.data:
            category = dict(row)
            categories.append(category)
        return categories

    def create(self, category_data):
        """Create a new category."""
        data = {
            'nome': category_data['name'],
            'descricao': category_data.get('description'),
            'categoria_pai_id': category_data.get('parent_category_id'),
            'nivel': category_data.get('nivel', 0),
            'caminho': category_data.get('path'),
            'ativo': category_data.get('ativo', True),
            'comercializavel': category_data.get('comercializavel', False),
            'componente': category_data.get('componente', False),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        query = self.table.insert(data)
        response = supabase_db.execute_with_retry(query)
        if response.data:
            result = dict(response.data[0])
            return result

        return None

    def update(self, category_id: str, category_data):
        """Update an existing category."""
        data = {
            'updated_at': datetime.utcnow().isoformat()
        }

        if 'name' in category_data:
            data['nome'] = category_data['name']
        if 'description' in category_data:
            data['descricao'] = category_data['description']
        if 'parent_category_id' in category_data:
            data['categoria_pai_id'] = category_data['parent_category_id']
        if 'nivel' in category_data:
            data['nivel'] = category_data['nivel']
        if 'path' in category_data:
            data['caminho'] = category_data['path']
        if 'ativo' in category_data:
            data['ativo'] = category_data['ativo']
        if 'comercializavel' in category_data:
            data['comercializavel'] = category_data['comercializavel']
        if 'componente' in category_data:
            data['componente'] = category_data['componente']

        query = self.table.update(data).eq('id', category_id)
        response = supabase_db.execute_with_retry(query)

        # Return updated category
        updated = self.get_by_id(category_id)
        return updated

    def delete(self, category_id: str):
        """Delete a category."""
        query = self.table.delete().eq('id', category_id)
        response = supabase_db.execute_with_retry(query)
        return len(response.data) > 0

# Global instance for use throughout the application
category_service = CategoryService()

