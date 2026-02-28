from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class ProdutoBlingVinculoService:
    """Service for managing product links with Bling (vinculos_bling) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            # Table name 'vinculos_bling' per schema
            self._table = supabase_db.table('vinculos_bling')
        return self._table

    def get_all_by_account(self, conta_bling_id: str):
        """Get all product links by Bling account."""
        # Query JSONB column 'configuracao_sync' for conta_bling_id?
        # Or assumes column 'conta_bling_id' exists?
        # Schema `db_schema.sql` says: 
        # CREATE TABLE vinculos_bling (..., produto_id, codigo_bling, configuracao_sync, ...)
        # It does NOT have `conta_bling_id` as a top-level column. It's likely in `configuracao_sync`.
        # Querying JSONB in Supabase:
        # .eq('configuracao_sync->>bling_account_id', conta_bling_id)
        
        response = self.table.select("*").eq('configuracao_sync->>bling_account_id', conta_bling_id).execute()

        links = []
        for row in response.data:
            link_data = dict(row)
            link_data['id'] = row.get('id')
            links.append(link_data)

        return links

    def get_by_product_and_account(self, produto_id: str, conta_bling_id: str):
        """Get product link by product and account."""
        # Assuming conta_bling_id is inside configuracao_sync
        response = self.table.select("*").eq('produto_id', produto_id).eq('configuracao_sync->>bling_account_id', conta_bling_id).execute()
        if response.data:
            link = dict(response.data[0])
            link['id'] = link.get('id')
            return link
        return None

    def get_by_bling_product(self, conta_bling_id: str, produto_bling_id: int):
        """Get product link by Bling product ID."""
        # Assuming produto_bling_id is inside configuracao_sync -> bling_product_id
        response = self.table.select("*").eq('configuracao_sync->>bling_account_id', conta_bling_id).eq('configuracao_sync->>bling_product_id', str(produto_bling_id)).execute()
        if response.data:
            link = dict(response.data[0])
            link['id'] = link.get('id')
            return link
        return None

    def get_all(self, conta_bling_id: str = None):
        """Get all product links, optionally filtered by account."""
        query = self.table.select("*")

        if conta_bling_id:
            query = query.eq('configuracao_sync->>bling_account_id', conta_bling_id)

        # Ordering by 'nome_bling' which is likely in configuracao_sync or a mapped column?
        # Schema doesn't show 'nome_bling'.
        # Try ordering by ID or updated_at if nome_bling not available.
        query = query.order('created_at', desc=True) 

        response = query.execute()

        links = []
        for row in response.data:
            link_data = dict(row)
            link_data['id'] = row.get('id')
            links.append(link_data)

        return links

    def create(self, vinculo_data):
        """Create a new product link."""
        # Check if link already exists
        existing = self.get_by_product_and_account(vinculo_data['produto_id'], vinculo_data['conta_bling_id'])
        if existing:
            raise ValueError('Product is already linked to this Bling account')

        # Check if Bling product is already linked
        existing_bling = self.get_by_bling_product(vinculo_data['conta_bling_id'], vinculo_data['produto_bling_id'])
        if existing_bling:
            raise ValueError('Bling product is already linked to another product')

        data = {
            'produto_id': vinculo_data['produto_id'],
            'codigo_bling': vinculo_data.get('sku_bling'), # Mapping sku_bling to codigo_bling
            'configuracao_sync': {
                'bling_account_id': vinculo_data['conta_bling_id'],
                'bling_product_id': vinculo_data['produto_bling_id'],
                'sku_bling': vinculo_data.get('sku_bling'),
                'nome_bling': vinculo_data.get('nome_bling'),
                'ativo': vinculo_data.get('ativo', True)
            },
            'status_sync': 'PENDENTE',
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            return result

        return None

    def update(self, link_id: str, vinculo_data):
        """Update an existing product link."""
        existing_response = self.table.select("*").eq('id', link_id).execute()
        if not existing_response.data:
            raise ValueError('Product link not found')
        
        existing_data = existing_response.data[0]
        config_sync = existing_data.get('configuracao_sync', {}) or {}

        update_data = {'updated_at': datetime.utcnow().isoformat()}

        field_mappings = {
            'sku_bling': 'sku_bling',
            'nome_bling': 'nome_bling',
            'ativo': 'ativo'
        }

        # Update JSONB fields
        for field, key in field_mappings.items():
            if field in vinculo_data:
                config_sync[key] = vinculo_data[field]
                
        # Update top level fields if necessary
        if 'sku_bling' in vinculo_data:
            update_data['codigo_bling'] = vinculo_data['sku_bling']
            
        update_data['configuracao_sync'] = config_sync

        response = self.table.update(update_data).eq('id', link_id).execute()

        # Return updated link
        return dict(response.data[0])

    def delete(self, link_id: str):
        """Delete a product link."""
        self.table.delete().eq('id', link_id).execute()
        return True

    def count_by_account(self, conta_bling_id: str):
        """Get count of product links by account."""
        response = self.table.select("count(*)", count='exact').eq('configuracao_sync->>bling_account_id', conta_bling_id).execute()
        return response.count if response.count is not None else 0

# Global instance for use throughout the application
produto_bling_vinculo_service = ProdutoBlingVinculoService()

