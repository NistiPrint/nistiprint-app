"""
Service for managing installed integration instances
"""
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
import requests
from google.cloud import secretmanager
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.platform_auth_service import platform_auth_service
from nistiprint_shared.services.integration_resolution_service import integration_resolution_service


class InstalledIntegrationService:
    """
    Service for managing user-installed integration instances
    """

    def __init__(self):
        self.table = supabase_db.table('installed_integrations')
        self.log_table = supabase_db.table('integration_refresh_logs')

    def _get_secret(self, secret_id: str, version_id: str = "latest") -> str:
        """
        Retrieves a secret from Google Cloud Secret Manager.
        """
        # Hardcoded project ID from existing scripts - ideally should be in config
        resource_project_id = "neolabs-nistiprint"
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{resource_project_id}/secrets/{secret_id}/versions/{version_id}"
        
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")

    def _refresh_bling_token(self, refresh_token: str, cnpj: str) -> Dict:
        """
        Refreshes Bling token using secrets derived from CNPJ.
        """
        if not cnpj or len(cnpj) < 5:
            raise ValueError("Invalid CNPJ for Bling token refresh")

        account_identifier = cnpj[:5]
        client_id = self._get_secret(f"BLING_CLIENT_ID_{account_identifier}")
        client_secret = self._get_secret(f"BLING_SECRET_{account_identifier}")

        url = "https://www.bling.com.br/Api/v3/oauth/token"
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        auth = (client_id, client_secret)

        response = requests.post(url, data=payload, auth=auth)
        response.raise_for_status()
        return response.json()

    def check_and_refresh_tokens(self) -> Dict:
        """
        Iterates through active integrations and attempts to refresh tokens.
        Currently supports: Bling.
        """
        results = {
            "processed": 0,
            "success": 0,
            "errors": 0,
            "skipped": 0
        }

        # Fetch all active integrations
        response = self.table.select("*").eq('is_active', True).execute()
        integrations = response.data

        for integration in integrations:
            results["processed"] += 1
            integration_id = integration.get('id')
            module_id = integration.get('module_id')
            
            try:
                if module_id == 'bling':
                    config = integration.get('config', {}) or {}
                    cnpj = config.get('cnpj')
                    
                    # Try to get refresh_token from top-level or credentials dict (fallback)
                    current_refresh_token = integration.get('refresh_token')
                    if not current_refresh_token:
                        creds = integration.get('credentials', {}) or {}
                        current_refresh_token = creds.get('refresh_token')

                    if not current_refresh_token:
                        raise ValueError("No refresh_token found")

                    # Refresh
                    new_tokens = self._refresh_bling_token(current_refresh_token, cnpj)
                    
                    # Update DB
                    update_data = {
                        'access_token': new_tokens['access_token'],
                        'refresh_token': new_tokens['refresh_token'],
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                        # Optionally update 'expires_in' if column exists or put in config/credentials
                    }
                    
                    self.update_installed(str(integration_id), update_data)
                    
                    # Log Success
                    self.log_table.insert({
                        'integration_id': integration_id,
                        'status': 'success',
                        'message': 'Token refreshed successfully',
                        'execution_mode': 'scheduled',
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }).execute()
                    
                    results["success"] += 1

                else:
                    # Other modules not yet supported for auto-refresh
                    results["skipped"] += 1

            except Exception as e:
                print(f"Error refreshing token for integration {integration_id}: {e}")
                results["errors"] += 1
                
                # Log Error
                try:
                    self.log_table.insert({
                        'integration_id': integration_id,
                        'status': 'error',
                        'message': str(e),
                        'execution_mode': 'scheduled',
                        'created_at': datetime.now(timezone.utc).isoformat()
                    }).execute()
                except Exception as log_error:
                    print(f"Failed to write log: {log_error}")

        return results

    def get_all_installed(self, user_id: str = None) -> List['InstalledIntegration']:
        """Get all installed integrations, optionally filtered by user"""
        query = self.table.select("*")
        if user_id:
            query = query.eq('user_id', user_id).eq('is_active', True)
        else:
            query = query.eq('is_active', True)

        response = query.execute()

        installations = []
        for row in response.data:
            installation_data = dict(row)
            instance_id = str(installation_data.get('id'))
            from nistiprint_shared.models.integration_module import InstalledIntegration
            installation = InstalledIntegration.from_dict(installation_data, instance_id)
            installations.append(installation)

        return installations

    def get_installed_by_id(self, instance_id: str) -> Optional['InstalledIntegration']:
        """Get a specific installed integration by ID"""
        response = self.table.select("*").eq('id', instance_id).execute()

        if response.data:
            installation_data = dict(response.data[0])
            from nistiprint_shared.models.integration_module import InstalledIntegration
            return InstalledIntegration.from_dict(installation_data, instance_id)

        return None

    def get_installed_by_user_and_module(self, user_id: str, module_id: str) -> List['InstalledIntegration']:
        """Get all installations of a specific module by a user"""
        response = self.table.select("*").eq('user_id', user_id).eq('module_id', module_id).execute()

        installations = []
        for row in response.data:
            installation_data = dict(row)
            instance_id = str(installation_data.get('id'))
            from nistiprint_shared.models.integration_module import InstalledIntegration
            installation = InstalledIntegration.from_dict(installation_data, instance_id)
            installations.append(installation)

        return installations

    def get_installed_by_module(self, module_id: str) -> List['InstalledIntegration']:
        """Get all installations of a specific module across all users"""
        response = self.table.select("*").eq('module_id', module_id).eq('is_active', True).execute()

        installations = []
        for row in response.data:
            installation_data = dict(row)
            instance_id = str(installation_data.get('id'))
            from nistiprint_shared.models.integration_module import InstalledIntegration
            installation = InstalledIntegration.from_dict(installation_data, instance_id)
            installations.append(installation)

        return installations

    def install_module(self, user_id: str, module_id: str, instance_name: str, config: Dict = None, credentials: Dict = None, instance_color: str = "#64748b", description: str = None) -> str:
        """Install a new instance of an integration module"""
        from nistiprint_shared.services.integration_module_service import integration_module_service

        # Verify the module exists and is active
        module = integration_module_service.get_module_by_id(module_id)
        if not module or not module.is_active:
            raise ValueError(f"Module {module_id} does not exist or is not active")

        # Check if instance name is unique for this user
        existing_installations = self.get_installed_by_user_and_module(user_id, module_id)
        for installation in existing_installations:
            if installation.instance_name == instance_name:
                raise ValueError(f"Instance name '{instance_name}' already exists for this module")

        # Create new installation
        from nistiprint_shared.models.integration_module import InstalledIntegration
        installation = InstalledIntegration(
            user_id=user_id,
            module_id=module_id,
            instance_name=instance_name,
            config=config or {},
            credentials=credentials or {},
            installation_date=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            instance_color=instance_color,
            description=description
        )

        installation_data = installation.to_dict()
        response = self.table.insert(installation_data).execute()
        if response.data:
            integration_resolution_service.invalidate()
            return str(response.data[0]['id'])
        return None

    def update_installed(self, instance_id: str, update_data: Dict) -> bool:
        """Update an existing installed integration"""
        update_data['updated_at'] = datetime.utcnow().isoformat()

        try:
            response = self.table.update(update_data).eq('id', instance_id).execute()
            if response.data:
                integration_resolution_service.invalidate()
            return len(response.data) > 0
        except Exception as e:
            print(f"Error updating installed integration {instance_id}: {e}")
            return False

    def renew_integration_token(self, instance_id: str, execution_mode: str = 'manual') -> Dict:
        """
        Renova o token de uma integração instalada usando o mesmo fluxo da UI.
        """
        inst = self.get_installed_by_id(instance_id)
        if not inst:
            raise ValueError("Integração não encontrada")

        now = datetime.utcnow()
        tokens = platform_auth_service.refresh_access_token(inst.module_id, inst.to_dict())
        expires_in = tokens.get('expires_in')

        merged_credentials = {
            **(inst.credentials or {}),
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
        }
        if expires_in is not None:
            merged_credentials['expires_in'] = expires_in

        update_data = {
            'credentials': merged_credentials,
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
            'last_refresh_attempt': now.isoformat(),
            'refresh_error': None,
        }
        if expires_in is not None:
            update_data['expires_at'] = (now + timedelta(seconds=expires_in)).isoformat()

        if not self.update_installed(instance_id, update_data):
            raise RuntimeError(f"Falha ao atualizar integração {instance_id} após renovar token")

        try:
            self.log_table.insert({
                'integration_id': instance_id,
                'status': 'success',
                'message': 'Token refreshed successfully',
                'execution_mode': execution_mode,
                'created_at': now.isoformat()
            }).execute()
        except Exception as log_error:
            print(f"Failed to write refresh success log for integration {instance_id}: {log_error}")

        return {
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
            'expires_in': expires_in,
            'expires_at': update_data.get('expires_at'),
        }

    def uninstall(self, instance_id: str) -> bool:
        """Uninstall an integration by setting is_active to False"""
        try:
            response = self.table.update({
                'is_active': False,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', instance_id).execute()
            if response.data:
                integration_resolution_service.invalidate()
            return len(response.data) > 0
        except Exception as e:
            print(f"Error uninstalling integration {instance_id}: {e}")
            return False

    def get_routing_for_function(self, marketplace_integration_id: str, function_scope: str = None) -> Optional['InstalledIntegration']:
        """
        Finds the integration responsible for a specific function (e.g. 'INVOICING') 
        related to a marketplace integration.
        
        Args:
            marketplace_integration_id (str): ID of the marketplace/e-commerce integration
            function_scope (str, optional): The specific function to route (e.g., 'INVOICING', 'ORDER_IMPORT')
            
        Returns:
            InstalledIntegration: The integration instance responsible for the function, or None.
        """
        from nistiprint_shared.models.integration_module import InstalledIntegration
        
        # 1. Check if the marketplace integration has a direct parent linked
        marketplace = self.get_installed_by_id(marketplace_integration_id)
        if marketplace and marketplace.parent_integration_id:
            parent = self.get_installed_by_id(str(marketplace.parent_integration_id))
            if parent:
                # If no scope specified, return the parent. 
                # If scope specified, check if parent handles it.
                if not function_scope or function_scope in (parent.functional_scopes or []):
                    return parent
        
        # 2. Fallback: Find the default integration that handles this scope
        if function_scope:
            try:
                response = self.table.select("*").eq('is_active', True).eq('is_default', True).execute()
                for row in response.data:
                    scopes = row.get('functional_scopes', []) or []
                    if function_scope in scopes:
                        return InstalledIntegration.from_dict(row, str(row['id']))
            except Exception as e:
                print(f"Error finding default integration for scope {function_scope}: {e}")
        
        # 3. Last fallback: If it's an ERP, it might handle its own functions
        if marketplace and function_scope:
            # Check if the marketplace itself has the scope (common for ERPs that are also import sources)
            if function_scope in (marketplace.functional_scopes or []):
                return marketplace

        return None

    def update_sync_status(self, instance_id: str, status: str, timestamp: datetime = None) -> bool:
        """Update the sync status of an installed integration"""
        update_data = {
            'sync_status': status,
            'last_sync': (timestamp or datetime.utcnow()).isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        try:
            response = self.table.update(update_data).eq('id', instance_id).execute()
            return len(response.data) > 0
        except Exception as e:
            print(f"Error updating sync status for {instance_id}: {e}")
            return False

    def get_installation_stats(self, module_id: str = None) -> Dict:
        """Get statistics about installed integrations"""
        query = self.table.select("*").eq('is_active', True)
        if module_id:
            query = query.eq('module_id', module_id)

        response = query.execute()
        installations = [dict(row) for row in response.data]

        stats = {
            'total_installations': len(installations),
            'by_user': {},
            'by_module': {},
            'by_status': {}
        }

        for installation in installations:
            user_id = installation.get('user_id')
            mod_id = installation.get('module_id')
            status = installation.get('sync_status', 'unknown')

            # Count by user
            if user_id in stats['by_user']:
                stats['by_user'][user_id] += 1
            else:
                stats['by_user'][user_id] = 1

            # Count by module
            if mod_id in stats['by_module']:
                stats['by_module'][mod_id] += 1
            else:
                stats['by_module'][mod_id] = 1

            # Count by status
            if status in stats['by_status']:
                stats['by_status'][status] += 1
            else:
                stats['by_status'][status] = 1

        return stats


# Global instance for use throughout the application
installed_integration_service = InstalledIntegrationService()

