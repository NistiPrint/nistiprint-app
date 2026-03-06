from nistiprint_shared.database.supabase_db_service import supabase_db
from datetime import datetime
import json
import logging

class AppConfigService:
    """Enhanced service for managing application configurations directly in Supabase with support for entity-specific configs."""

    def __init__(self):
        self.table = supabase_db.table('configuracoes_aplicacao')

    def get_config(self, key: str, entidade_tipo: str = None, entidade_id: int = None):
        """Get a configuration value by its key, optionally scoped to a specific entity."""
        try:
            query = self.table.select("valor").eq('nome', key)

            # Apply entity scoping if provided
            if entidade_tipo is not None and entidade_id is not None:
                query = query.eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id)
            else:
                # For global configs, ensure entidade_tipo and entidade_id are NULL
                query = query.is_('entidade_tipo', 'null').is_('entidade_id', 'null')

            response = supabase_db.execute_with_retry(query)

            if response.data:
                config_row = response.data[0]
                valor = config_row.get('valor')
                # If valor is a dict/list, return as is; if string, try to parse as JSON
                if isinstance(valor, str):
                    try:
                        return json.loads(valor)
                    except (json.JSONDecodeError, TypeError):
                        return valor
                return valor
            return None
        except Exception as e:
            logging.error(f"Error getting config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {e}")
            return None

    def set_config(self, key: str, value, entidade_tipo: str = None, entidade_id: int = None):
        """Set a configuration value for a given key, optionally scoped to a specific entity."""
        try:
            # If value is None, delete the config entry to avoid null constraint violations
            if value is None:
                return self.delete_config(key, entidade_tipo, entidade_id)

            # Convert value to JSON string if it's a dict/list, otherwise keep as is
            valor_to_store = json.dumps(value) if isinstance(value, (dict, list)) else value

            data = {
                'nome': key,
                'valor': valor_to_store,
                'updated_at': datetime.utcnow().isoformat()
            }

            # Add entity scoping if provided
            if entidade_tipo is not None and entidade_id is not None:
                data['entidade_tipo'] = entidade_tipo
                data['entidade_id'] = entidade_id
            else:
                # For global configs, ensure these are NULL
                data['entidade_tipo'] = None
                data['entidade_id'] = None

            # Check if the config already exists
            query = self.table.select("id").eq('nome', key)
            if entidade_tipo is not None and entidade_id is not None:
                query = query.eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id)
            else:
                query = query.is_('entidade_tipo', 'null').is_('entidade_id', 'null')
            
            existing_response = query.execute()

            if existing_response.data:
                # Update existing config
                update_query = self.table.update(data).eq('nome', key)
                if entidade_tipo is not None and entidade_id is not None:
                    update_query = update_query.eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id)
                else:
                    update_query = update_query.is_('entidade_tipo', 'null').is_('entidade_id', 'null')
                
                response = update_query.execute()
                logging.info(f"Updated config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'} successfully")
            else:
                # Insert new config
                data['created_at'] = datetime.utcnow().isoformat()
                # For global configs, ensure entity fields are properly set to NULL
                if entidade_tipo is None and entidade_id is None:
                    data['entidade_tipo'] = None
                    data['entidade_id'] = None
                response = self.table.insert(data).execute()
                logging.info(f"Inserted config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'} successfully")

            return data
        except Exception as e:
            logging.error(f"Error setting config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {e}")
            raise e

    def delete_config(self, key: str, entidade_tipo: str = None, entidade_id: int = None):
        """Delete a configuration entry by its key, optionally scoped to a specific entity."""
        try:
            delete_query = self.table.delete().eq('nome', key)
            
            if entidade_tipo is not None and entidade_id is not None:
                delete_query = delete_query.eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id)
            else:
                delete_query = delete_query.is_('entidade_tipo', 'null').is_('entidade_id', 'null')

            response = delete_query.execute()
            success = len(response.data) > 0
            if success:
                logging.info(f"Deleted config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'} successfully")
            else:
                logging.warning(f"Attempted to delete non-existent config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'}")
            return success
        except Exception as e:
            logging.error(f"Error deleting config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {e}")
            raise e

    def get_multiple_configs(self, keys: list, entidade_tipo: str = None, entidade_id: int = None):
        """Get multiple configuration values by their keys, optionally scoped to a specific entity."""
        try:
            query = self.table.select("nome, valor").in_("nome", keys)

            # Apply entity scoping if provided
            if entidade_tipo is not None and entidade_id is not None:
                query = query.eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id)
            else:
                query = query.is_('entidade_tipo', 'null').is_('entidade_id', 'null')

            response = query.execute()
            configs = {}
            for row in response.data:
                key = row['nome']
                valor = row['valor']
                # Parse JSON if it's a string
                if isinstance(valor, str):
                    try:
                        configs[key] = json.loads(valor)
                    except (json.JSONDecodeError, TypeError):
                        configs[key] = valor
                else:
                    configs[key] = valor
            return configs
        except Exception as e:
            logging.error(f"Error getting multiple configs {keys} for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {e}")
            return {}

    def set_multiple_configs(self, configs_dict: dict, entidade_tipo: str = None, entidade_id: int = None):
        """Set multiple configuration values at once, optionally scoped to a specific entity."""
        results = []
        errors = []

        for key, value in configs_dict.items():
            try:
                result = self.set_config(key, value, entidade_tipo, entidade_id)
                results.append(result)
            except Exception as e:
                logging.error(f"Error setting config '{key}' for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {e}")
                errors.append({'key': key, 'error': str(e)})

        if errors:
            logging.error(f"Errors occurred while setting configs for {entidade_tipo}:{entidade_id if entidade_id else 'global'}: {errors}")
            raise Exception(f"Errors occurred while setting configs: {errors}")

        return results

    def get_entity_configs(self, entidade_tipo: str, entidade_id: int):
        """Get all configurations for a specific entity."""
        try:
            response = self.table.select("nome, valor").eq('entidade_tipo', entidade_tipo).eq('entidade_id', entidade_id).execute()
            configs = {}
            for row in response.data:
                key = row['nome']
                valor = row['valor']
                # Parse JSON if it's a string
                if isinstance(valor, str):
                    try:
                        configs[key] = json.loads(valor)
                    except (json.JSONDecodeError, TypeError):
                        configs[key] = valor
                else:
                    configs[key] = valor
            return configs
        except Exception as e:
            logging.error(f"Error getting configs for {entidade_tipo}:{entidade_id}: {e}")
            return {}

    def get_operational_mode(self):
        """
        Returns the current database operational mode ('v2' or 'legacy').
        Defaults to 'v2' (Supabase).
        """
        mode = self.get_config('database_operational_mode')
        return mode if mode in ['v2', 'legacy'] else 'v2'

    def migrate_json_configs(self, source_table: str, source_column: str, target_entity_type: str):
        """
        Helper method to migrate configurations from JSON columns in other tables
        to the standardized configuracoes_aplicacao table.
        """
        try:
            # This would be called to migrate configurations from platforms, channels, etc.
            # Implementation would depend on the specific source table structure
            logging.info(f"Starting migration of {source_column} from {source_table} to configuracoes_aplicacao as {target_entity_type}")
            # Actual implementation would involve reading from the source table,
            # extracting individual config values from JSON, and inserting them
            # as separate rows in configuracoes_aplicacao with appropriate entity references
        except Exception as e:
            logging.error(f"Error migrating configs from {source_table}.{source_column}: {e}")
            raise e

# Global instance for use throughout the application
app_config_service = AppConfigService()

