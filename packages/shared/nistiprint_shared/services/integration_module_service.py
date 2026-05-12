"""
Service for managing integration modules in the marketplace
"""
from typing import List, Dict, Optional
from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
from modules.platform_modules import get_all_platform_modules


class IntegrationModuleService:
    """
    Service for managing available integration modules in the marketplace
    """

    def __init__(self):
        self.table = supabase_db.table('integration_modules')

    def get_all_modules(self) -> List['IntegrationModule']:
        """Get all available integration modules, combining database and hardcoded modules"""
        from nistiprint_shared.models.integration_module import IntegrationModule
        
        # Start with hardcoded platform modules
        modules = get_all_platform_modules()
        
        # Ensure hardcoded modules have IDs that match their names for routing
        for mod in modules:
            if not mod.id:
                mod.id = mod.name.lower().replace(' ', '_').replace('_integration', '')

        try:
            # Try to fetch additional modules from nistiprint_shared.database
            response = self.table.select("*").eq('is_active', True).execute()
            
            for row in response.data:
                module_data = dict(row)
                module_id = str(module_data.get('id'))
                # Avoid duplicates if hardcoded module has same ID as database module
                if not any(m.id == module_id for m in modules):
                    module = IntegrationModule.from_dict(module_data, module_id)
                    modules.append(module)
        except Exception as e:
            print(f"Note: Could not fetch integration_modules from DB (might not exist yet): {e}")

        return modules

    def get_module_by_id(self, module_id: str) -> Optional['IntegrationModule']:
        """Get a specific integration module by ID"""
        # First check hardcoded modules
        all_modules = self.get_all_modules()
        for module in all_modules:
            if module.id == module_id:
                return module

        # Then check database
        try:
            response = self.table.select("*").eq('id', module_id).execute()
            if response.data:
                module_data = dict(response.data[0])
                from nistiprint_shared.models.integration_module import IntegrationModule
                return IntegrationModule.from_dict(module_data, module_id)
        except Exception:
            pass

        return None

    def get_modules_by_category(self, category: str) -> List['IntegrationModule']:
        """Get all modules in a specific category"""
        from nistiprint_shared.models.integration_module import IntegrationModule

        response = self.table.select("*").eq('category', category).eq('is_active', True).execute()

        modules = []
        for row in response.data:
            module_data = dict(row)
            module_id = str(module_data.get('id'))
            module = IntegrationModule.from_dict(module_data, module_id)
            modules.append(module)

        return modules

    def get_modules_by_tags(self, tags: List[str]) -> List['IntegrationModule']:
        """Get modules that match any of the provided tags"""
        # Note: We'll get all active modules and filter in memory
        from nistiprint_shared.models.integration_module import IntegrationModule

        all_modules = self.get_all_modules()
        filtered_modules = []

        for module in all_modules:
            if any(tag in module.tags for tag in tags):
                filtered_modules.append(module)

        return filtered_modules

    def create_module(self, module: 'IntegrationModule') -> str:
        """Create a new integration module"""
        module.created_at = datetime.utcnow()
        module.updated_at = datetime.utcnow()

        module_data = module.to_dict()
        module_data['id'] = module.id
        response = self.table.insert(module_data).execute()
        if response.data:
            return str(response.data[0]['id'])
        return None

    def update_module(self, module_id: str, update_data: Dict) -> bool:
        """Update an existing integration module"""
        update_data['updated_at'] = datetime.utcnow()

        try:
            response = self.table.update(update_data).eq('id', module_id).execute()
            return len(response.data) > 0
        except Exception:
            return False

    def delete_module(self, module_id: str) -> bool:
        """Soft delete an integration module by setting is_active to False"""
        try:
            response = self.table.update({
                'is_active': False,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', module_id).execute()
            return len(response.data) > 0
        except Exception:
            return False

    def activate_module(self, module_id: str) -> bool:
        """Activate an integration module"""
        try:
            response = self.table.update({
                'is_active': True,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', module_id).execute()
            return len(response.data) > 0
        except Exception:
            return False


# Global instance for use throughout the application
integration_module_service = IntegrationModuleService()

