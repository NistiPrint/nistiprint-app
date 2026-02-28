from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class FornecedorService:
    """Service for managing suppliers (fornecedores) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            self._table = supabase_db.table('fornecedores')
        return self._table

    def get_all(self, page: int = 1, per_page: int = 50):
        """Get all suppliers with pagination."""
        offset = (page - 1) * per_page
        
        # Order by nome (which matches 'nome' column in Supabase schema vs 'nome_razao_social' in Firestore)
        # Schema `db_schema.sql` says: `nome VARCHAR(255) NOT NULL`.
        # Code used `nome_razao_social`. I will map it.
        
        response = self.table.select("*").order('nome', desc=False).range(offset, offset + per_page - 1).execute()

        suppliers = []
        for row in response.data:
            supplier_data = dict(row)
            supplier_data['id'] = row.get('id')
            # Map back to 'nome_razao_social' for compatibility if needed, or update frontend?
            # Ideally frontend uses 'nome'. But to avoid breaking, I'll add alias.
            supplier_data['nome_razao_social'] = supplier_data.get('nome')
            suppliers.append(supplier_data)

        return suppliers

    def get_by_id(self, supplier_id: str):
        """Get supplier by ID."""
        response = self.table.select("*").eq('id', supplier_id).execute()
        if response.data:
            supplier = dict(response.data[0])
            supplier['id'] = supplier.get('id')
            supplier['nome_razao_social'] = supplier.get('nome')
            return supplier
        return None

    def search(self, query: str):
        """Search suppliers by name or document."""
        if not query:
            return []
            
        # Using ilike for search
        # Search in 'nome' and 'cnpj' (schema says 'cnpj', code used 'cpf_cnpj')
        response = self.table.select("*").or_(f"nome.ilike.%{query}%,cnpj.ilike.%{query}%").execute()
        
        results = []
        for row in response.data:
            supplier = dict(row)
            supplier['id'] = row.get('id')
            supplier['nome_razao_social'] = supplier.get('nome')
            supplier['cpf_cnpj'] = supplier.get('cnpj')
            results.append(supplier)

        return results

    def create(self, supplier_data):
        """Create a new supplier."""
        # Use 'nome_razao_social' as 'nome', and 'cpf_cnpj' as 'cnpj'
        nome = supplier_data.get('nome_razao_social') or supplier_data.get('nome')
        cnpj = supplier_data.get('cpf_cnpj') or supplier_data.get('cnpj')
        
        # Check document uniqueness if provided
        if cnpj:
            existing = self.get_by_document(cnpj)
            if existing:
                raise ValueError(f"Supplier with document '{cnpj}' already exists")

        # Prepare data
        data = {
            'nome': nome,
            'cnpj': cnpj,
            'informacoes_contato': {
                'email': supplier_data.get('email'),
                'telefone': supplier_data.get('telefone')
            },
            # Schema has 'informacoes_contato' JSONB, but let's try to map nicely if columns don't exist
            # Wait, schema has: nome, cnpj, contato_principal, informacoes_contato, categoria, classificacao, ativo, dados_contratuais
            # It does NOT have email/telefone columns directly.
            'ativo': supplier_data.get('ativo', True),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            result['nome_razao_social'] = result.get('nome')
            return result

        return None

    def update(self, supplier_id: str, supplier_data):
        """Update an existing supplier."""
        nome = supplier_data.get('nome_razao_social') or supplier_data.get('nome')
        cnpj = supplier_data.get('cpf_cnpj') or supplier_data.get('cnpj')

        # Check document uniqueness if being updated
        if cnpj:
            existing = self.get_by_document(cnpj)
            if existing and str(existing['id']) != str(supplier_id):
                raise ValueError(f"Supplier with document '{cnpj}' already exists")

        # Get existing supplier
        existing = self.get_by_id(supplier_id)
        if not existing:
            raise ValueError(f"Supplier with ID '{supplier_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        if nome:
            update_data['nome'] = nome
        if cnpj:
            update_data['cnpj'] = cnpj
        if 'ativo' in supplier_data:
            update_data['ativo'] = supplier_data['ativo']
            
        # Update contacts
        current_contacts = existing.get('informacoes_contato') or {}
        if 'email' in supplier_data: current_contacts['email'] = supplier_data['email']
        if 'telefone' in supplier_data: current_contacts['telefone'] = supplier_data['telefone']
        
        update_data['informacoes_contato'] = current_contacts

        self.table.update(update_data).eq('id', supplier_id).execute()

        # Return updated supplier
        return self.get_by_id(supplier_id)

    def delete(self, supplier_id: str):
        """Soft delete a supplier by setting ativo to False."""
        self.table.update({
            'ativo': False,
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', supplier_id).execute()

        return True

    def get_by_document(self, cpf_cnpj: str):
        """Get supplier by CPF/CNPJ."""
        response = self.table.select("*").eq('cnpj', cpf_cnpj).execute()
        if response.data:
            supplier = dict(response.data[0])
            supplier['id'] = supplier.get('id')
            supplier['nome_razao_social'] = supplier.get('nome')
            return supplier
        return None

    def count(self):
        """Get total count of suppliers."""
        response = self.table.select("count(*)", count='exact').execute()
        return response.count if response.count is not None else 0

# Global instance for use throughout the application
fornecedor_service = FornecedorService()

