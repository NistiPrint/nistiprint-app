from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime

class ContaBlingService:
    """Service for managing Bling accounts (contas Bling) in Supabase."""

    def __init__(self):
        self._table = None

    @property
    def table(self):
        """Lazy initialization of table."""
        if self._table is None:
            # Update to use the correct table name 'contas_bling'
            self._table = supabase_db.table('contas_bling')
        return self._table

    def get_all(self):
        """Get all Bling accounts ordered by name."""
        # Order by 'nome' instead of 'account_name'
        response = self.table.select("*").order("nome", desc=False).execute()

        accounts = []
        for row in response.data:
            account = dict(row)
            account['id'] = row.get('id')
            # Map 'nome' to 'account_name' for compatibility
            account['account_name'] = row.get('nome')
            # Safely get CNPJ or default to empty string/placeholder
            account['cnpj'] = row.get('cnpj', 'N/A')
            accounts.append(account)

        return accounts

    def get_by_id(self, account_id: str):
        """Get Bling account by ID."""
        response = self.table.select("*").eq('id', account_id).execute()
        if response.data:
            account = dict(response.data[0])
            account['id'] = account.get('id')
            return account
        return None

    def get_by_cnpj(self, cnpj: str):
        """Get Bling account by CNPJ."""
        response = self.table.select("*").eq('cnpj', cnpj).execute()
        if response.data:
            account = dict(response.data[0])
            account['id'] = account.get('id')
            return account
        return None

    def get_by_platform(self, platform: str):
        """Get all Bling accounts for a specific platform."""
        response = self.table.select("*").eq('platform_name', platform).execute()

        accounts = []
        for row in response.data:
            account = dict(row)
            account['id'] = account.get('id')
            accounts.append(account)

        return accounts

    def get_by_platform_and_instance(self, platform: str, instance_name: str = None):
        """Get Bling account by platform and optional instance name."""
        query = self.table.select("*").eq('platform_name', platform)

        if instance_name:
            query = query.eq('instance_name', instance_name)

        response = query.execute()

        if response.data:
            account = dict(response.data[0])
            account['id'] = account.get('id')
            return account

        return None

    def create(self, account_data):
        """Create a new Bling account."""
        # Check CNPJ uniqueness
        existing = self.get_by_cnpj(account_data['cnpj'])
        if existing:
            raise ValueError(f"Bling account with CNPJ '{account_data['cnpj']}' already exists")

        # Prepare data - adaptar para os campos existentes
        data = {
            'account_name': account_data['account_name'],
            'cnpj': account_data['cnpj'],
            'client_id': account_data.get('client_id'),
            'client_secret': account_data.get('client_secret'),
            'access_token': account_data.get('access_token'),
            'refresh_token': account_data.get('refresh_token'),
            'expires_in': account_data.get('expires_in'),
            'platform_name': account_data.get('platform_name'),
            'icon_url': account_data.get('icon_url'),
            'instance_name': account_data.get('instance_name', ''),  # New field for multiple instances
            'versao_api': account_data.get('versao_api', ''),  # New field for API version
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        response = self.table.insert(data).execute()
        if response.data:
            result = dict(response.data[0])
            result['id'] = result.get('id')
            return result

        return None

    def update(self, account_id: str, account_data):
        """Update an existing Bling account."""
        # Check CNPJ uniqueness if being updated
        if 'cnpj' in account_data:
            existing = self.get_by_cnpj(account_data['cnpj'])
            if existing and existing['id'] != account_id:
                raise ValueError(f"Bling account with CNPJ '{account_data['cnpj']}' already exists")

        # Get existing account
        existing = self.get_by_id(account_id)
        if not existing:
            raise ValueError(f"Bling account with ID '{account_id}' not found")

        # Prepare update data
        update_data = {'updated_at': datetime.utcnow().isoformat()}

        # Mapear campos para os nomes existentes
        field_mappings = {
            'account_name': 'account_name',
            'cnpj': 'cnpj',
            'client_id': 'client_id',
            'client_secret': 'client_secret',
            'access_token': 'access_token',
            'refresh_token': 'refresh_token',
            'expires_in': 'expires_in',
            'platform_name': 'platform_name',
            'icon_url': 'icon_url',
            'store_mappings': 'store_mappings',
            'instance_name': 'instance_name',
            'versao_api': 'versao_api'
        }

        for field, key in field_mappings.items():
            if field in account_data:
                update_data[key] = account_data[field]

        response = self.table.update(update_data).eq('id', account_id).execute()

        # Return updated account
        return self.get_by_id(account_id)

    def delete(self, account_id: str):
        """Delete a Bling account."""
        existing = self.get_by_id(account_id)
        if not existing:
            raise ValueError(f"Bling account with ID '{account_id}' not found")

        response = self.table.delete().eq('id', account_id).execute()
        return len(response.data) > 0

    def count(self):
        """Get total count of Bling accounts."""
        response = self.table.select("count(*)").execute()
        if response.data:
            return response.data[0]['count']
        return 0

    def update_tokens(self, account_id: str, access_token: str, refresh_token: str = None, expires_in: int = None):
        """Update tokens for a Bling account."""
        update_data = {
            'access_token': access_token,
            'updated_at': datetime.utcnow().isoformat()
        }

        if refresh_token:
            update_data['refresh_token'] = refresh_token
        if expires_in:
            update_data['expires_in'] = expires_in

        response = self.table.update(update_data).eq('id', account_id).execute()
        return self.get_by_id(account_id)

# Global instance for use throughout the application
conta_bling_service = ContaBlingService()

