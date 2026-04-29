"""
Supabase Database Service that maintains SQLAlchemy-like interface for backward compatibility
"""
import os
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar
from supabase import create_client, Client
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
import logging
import httpx

# Generic type variable for model classes
T = TypeVar('T')

class SupabaseDBService:
    """
    A database service that provides a SQLAlchemy-like interface
    but uses Supabase/PostgreSQL as the underlying database.
    """

    def __init__(self, url=None, key=None):
        self.supabase_url = url or os.environ.get('SUPABASE_URL')
        self.supabase_key = key or os.environ.get('SUPABASE_SERVICE_KEY')
        self.client = None

        # Circuit breaker state
        self._pool_timeout_count = 0
        self._last_pool_timeout_time = 0
        self._circuit_broken_until = 0

        if self.supabase_url and self.supabase_key:
            try:
                self.client: Client = create_client(
                    self.supabase_url,
                    self.supabase_key
                )
                logging.info("Successfully connected to Supabase")
            except Exception as e:
                logging.error(f"Failed to connect to Supabase: {e}")
        else:
            logging.warning("SUPABASE_URL and SUPABASE_SERVICE_KEY not set during initialization. Supabase operations will fail unless variables are set later.")

    def _ensure_client(self):
        """
        Ensure that the Supabase client is initialized.
        This allows for late initialization if variables were not set during __init__.
        """
        if self.client:
            return True

        self.supabase_url = self.supabase_url or os.environ.get('SUPABASE_URL')
        self.supabase_key = self.supabase_key or os.environ.get('SUPABASE_SERVICE_KEY')

        if not self.supabase_url or not self.supabase_key:
            logging.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables")
            return False

        try:
            from supabase import create_client
            self.client: Client = create_client(
                self.supabase_url,
                self.supabase_key
            )
            logging.info("Supabase client initialized via late-binding.")
            return True
        except Exception as e:
            logging.error(f"Failed to late-initialize Supabase client: {e}")
            return False

    def execute_with_retry(self, query, max_retries=3, base_delay=0.5):
        """
        Execute a Supabase/PostgREST query with retry logic for connection errors.
        Includes a circuit breaker for PoolTimeout.
        """
        if not self._ensure_client():
            raise ValueError("Supabase client is not initialized and environment variables are missing.")
            
        import time
        import httpx
        import ssl

        # Check circuit breaker
        current_time = time.time()
        if self._circuit_broken_until > current_time:
            wait_time = self._circuit_broken_until - current_time
            logging.warning(f"Supabase circuit breaker active. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

        last_exception = None
        for attempt in range(max_retries):
            try:
                return query.execute()
            except httpx.PoolTimeout as e:
                last_exception = e
                # Circuit breaker logic: 3 timeouts in 30s -> break for 5s
                self._pool_timeout_count += 1
                if current_time - self._last_pool_timeout_time > 30:
                    self._pool_timeout_count = 1
                self._last_pool_timeout_time = current_time

                if self._pool_timeout_count >= 3:
                    self._circuit_broken_until = current_time + 5.0
                    logging.error("Supabase PoolTimeout circuit breaker triggered! Backing off for 5s.")
                    break # Don't retry this specific call anymore
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.TimeoutException,
                    httpx.ReadTimeout, ssl.SSLError, httpx.WriteError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logging.warning(f"Supabase connection error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logging.error(f"Supabase connection failed after {max_retries} attempts: {e}")
            except Exception as e:
                error_msg = str(e).lower()
                if any(keyword in error_msg for keyword in ['server disconnected', 'connection reset', 'broken pipe', 'connection aborted', 'handshake']):
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logging.warning(f"Supabase connection error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        logging.error(f"Supabase connection failed after {max_retries} attempts: {e}")
                else:
                    raise e
        raise last_exception

    def table(self, table_name: str):
        """
        Get a table reference for performing operations
        """
        if not self._ensure_client():
            raise ValueError("Supabase client not initialized and environment variables are missing.")
        return self.client.table(table_name)

    def rpc(self, function_name: str, params: Optional[Dict[str, Any]] = None):
        """
        Call a Postgres function via RPC
        """
        if not self._ensure_client():
            raise ValueError("Supabase client not initialized and environment variables are missing.")
        return self.client.rpc(function_name, params or {})

    def get(self, table_name: str, id: int):
        """
        Get a record by ID
        """
        if not self._ensure_client():
             return None
        try:
            query = self.client.table(table_name).select("*").eq("id", id).single()
            response = self.execute_with_retry(query)
            return response.data if response.data else None
        except Exception as e:
            print(f"Error getting record from {table_name} with id {id}: {e}")
            return None

    def get_all(self, table_name: str, filters: Optional[Dict] = None):
        """
        Get all records from a table with optional filters
        """
        if not self._ensure_client():
            return []
        try:
            query = self.client.table(table_name).select("*")

            if filters:
                for key, value in filters.items():
                    # Handle different value types explicitly for Supabase compatibility
                    try:
                        if isinstance(value, bool):
                            # Convert Python boolean to appropriate format for Supabase
                            query = query.eq(key, value)
                        elif value is None:
                            # Handle null values
                            query = query.is_(key, None)
                        else:
                            query = query.eq(key, value)
                    except Exception as filter_error:
                        print(f"Error applying filter {key}={value} (type: {type(value)}): {filter_error}")
                        raise

            response = self.execute_with_retry(query)
            return response.data
        except Exception as e:
            print(f"Error getting records from {table_name} with filters {filters}: {e}")
            return []

    def get_by_field(self, table_name: str, field: str, value: Any):
        """
        Get records by a specific field and value (convenience method)
        """
        return self.get_all(table_name, {field: value})

    def get_by_fields(self, table_name: str, filters: Dict[str, Any]):
        """
        Get records by multiple fields (alias for get_all with filters)
        """
        return self.get_all(table_name, filters)

    def insert(self, table_name: str, data: Dict[str, Any]):
        """
        Insert a new record
        """
        try:
            query = self.client.table(table_name).insert(data)
            response = self.execute_with_retry(query)
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error inserting record into {table_name}: {e}")
            return None

    def update(self, table_name: str, id: int, data: Dict[str, Any]):
        """
        Update a record by ID
        """
        try:
            query = self.client.table(table_name).update(data).eq("id", id)
            response = self.execute_with_retry(query)
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error updating record in {table_name} with id {id}: {e}")
            return None

    def delete(self, table_name: str, id: int):
        """
        Delete a record by ID
        """
        try:
            query = self.client.table(table_name).delete().eq("id", id)
            response = self.execute_with_retry(query)
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error deleting record from {table_name} with id {id}: {e}")
            return None

    def query(self, table_name: str):
        """
        Start building a query for a table
        """
        return self.client.table(table_name).select("*")


# Global instance of the Supabase service
supabase_db = SupabaseDBService()


class SupabaseQueryInterface:
    def __init__(self, model_class):
        self.model_class = model_class
        self.table_name = getattr(model_class, '__tablename__', model_class.__name__.lower())
        self.filters = {}

    def filter_by(self, **kwargs):
        # Create a new instance of the query interface with filters
        filtered_query = SupabaseQueryInterface(self.model_class)
        filtered_query.table_name = self.table_name
        filtered_query.filters = getattr(self, 'filters', {}).copy()
        filtered_query.filters.update(kwargs)
        return filtered_query

    def order_by(self, field):
        # Handle order_by for Supabase query interface
        filtered_query = SupabaseQueryInterface(self.model_class)
        filtered_query.table_name = self.table_name
        filtered_query.filters = getattr(self, 'filters', {}).copy()

        # Handle different types of field specifications
        field_name = None
        is_descending = False

        # Try to determine if this is a descending order expression
        # Common patterns for SQLAlchemy descending expressions:
        field_str = str(field).lower()

        # Check if it contains 'desc' indicating descending order
        if 'desc' in field_str or 'descending' in field_str:
            is_descending = True

        # Try to extract field name from different possible structures
        if hasattr(field, 'element') and hasattr(field, 'name'):
            # This might be a descending expression like column.desc()
            if hasattr(field.element, 'name'):
                field_name = field.element.name
            else:
                # Fallback to string parsing
                field_name = field_str.split('.')[-1].replace(' desc', '').replace(' descending', '').strip()
        elif hasattr(field, 'name'):
            # Regular column object
            field_name = field.name
        else:
            # Handle string-based field specification
            # Extract field name from string like "Setor.nome"
            field_parts = field_str.split('.')
            field_name = field_parts[-1] if len(field_parts) > 1 else field_str
            # Clean up any order indicators from the field name
            field_name = field_name.replace(' desc', '').replace(' descending', '').strip()

        # Clean up field name if it starts with '-' (for manual descending)
        if field_name.startswith('-'):
            field_name = field_name[1:]

        filtered_query.order_by_field = field_name
        filtered_query.order_by_desc = is_descending
        return filtered_query

    def filter(self, *conditions):
        # Handle SQLAlchemy-style filter conditions
        # For now, support basic comparison conditions like Usuario.id != usuario_id
        filtered_query = SupabaseQueryInterface(self.model_class)
        filtered_query.table_name = self.table_name
        filtered_query.filters = getattr(self, 'filters', {}).copy()
        filtered_query.in_filters = getattr(self, 'in_filters', {}).copy()  # For IN operations

        for condition in conditions:
            # Parse SQLAlchemy condition objects
            if hasattr(condition, 'left') and hasattr(condition, 'right'):
                # Handle binary expressions like Usuario.id != usuario_id
                left_expr = condition.left
                right_expr = condition.right
                op = condition.operator

                # Extract field name from left side
                field_name = str(left_expr).split('.')[-1] if hasattr(left_expr, 'name') else str(left_expr)

                # Handle different operators
                if hasattr(right_expr, 'value'):
                    value = right_expr.value
                else:
                    value = right_expr

                # For inequality conditions, we'll need to handle them specially
                # Since Supabase client doesn't directly support !=, we'll store them differently
                if op.__name__ == 'ne':  # != operator
                    # Store as a special filter for inequality
                    if not hasattr(filtered_query, 'not_filters'):
                        filtered_query.not_filters = {}
                    filtered_query.not_filters[field_name] = value
                elif op.__name__ == 'eq':  # == operator
                    filtered_query.filters[field_name] = value
                elif op.__name__ == 'in_op':  # IN operator
                    # Store as a special filter for IN operations
                    if not hasattr(filtered_query, 'in_filters'):
                        filtered_query.in_filters = {}
                    # Handle the case where value might be a list
                    if hasattr(value, '__iter__') and not isinstance(value, str):
                        filtered_query.in_filters[field_name] = list(value)
                    else:
                        filtered_query.in_filters[field_name] = [value]
                # Add more operators as needed
            else:
                # Handle simpler cases where condition might be a direct comparison
                # This is a simplified approach for common patterns
                condition_str = str(condition)
                if '!=' in condition_str:
                    # Parse "Usuario.id != value" style conditions
                    parts = condition_str.split(' != ')
                    if len(parts) == 2:
                        field_part = parts[0].strip()
                        field_name = field_part.split('.')[-1] if '.' in field_part else field_part
                        # For !=, store in not_filters
                        if not hasattr(filtered_query, 'not_filters'):
                            filtered_query.not_filters = {}
                        try:
                            # Try to convert to int if it looks like a number
                            value = int(parts[1].strip())
                        except ValueError:
                            # Remove quotes if present
                            value = parts[1].strip().strip("'\"")
                        filtered_query.not_filters[field_name] = value
                        
                elif '==' in condition_str:
                    parts = condition_str.split(' == ')
                    if len(parts) == 2:
                        field_part = parts[0].strip()
                        field_name = field_part.split('.')[-1] if '.' in field_part else field_part
                        try:
                            value = int(parts[1].strip())
                        except ValueError:
                            value = parts[1].strip().strip("'\"")
                        filtered_query.filters[field_name] = value
                        
                elif '.in_(' in condition_str:
                    # Parse "Recurso.id.in_(list)" style conditions
                    # This is a simplified parsing - in a real implementation you'd want more robust parsing
                    import re
                    match = re.search(r'(\w+)\.in_(\[.*\]|.*)', condition_str)
                    if match:
                        field_part = match.group(1)
                        field_name = field_part.split('.')[-1] if '.' in field_part else field_part
                        list_str = match.group(2)

                        # Try to parse the list - this is simplified
                        if list_str.startswith('[') and list_str.endswith(']'):
                            # Simple list parsing - in real world you'd want more robust parsing
                            try:
                                # Remove brackets and split by comma
                                inner_list = list_str[1:-1].split(',')
                                parsed_list = []
                                for item in inner_list:
                                    item = item.strip().strip("'\"")
                                    try:
                                        parsed_list.append(int(item))
                                    except ValueError:
                                        parsed_list.append(item)
                                if not hasattr(filtered_query, 'in_filters'):
                                    filtered_query.in_filters = {}
                                filtered_query.in_filters[field_name] = parsed_list
                            except:
                                # If parsing fails, try to handle as a simple list
                                if not hasattr(filtered_query, 'in_filters'):
                                    filtered_query.in_filters = {}
                                filtered_query.in_filters[field_name] = [list_str]

        return filtered_query

    def first(self):
        # Get all records with filters and return the first one
        filters = getattr(self, 'filters', {})
        not_filters = getattr(self, 'not_filters', {})
        in_filters = getattr(self, 'in_filters', {})

        # Apply filters to get initial results
        results = supabase_db.get_all(self.table_name, filters)
        
        # Apply in_filters (IN operations) by filtering in Python
        if in_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value_list in in_filters.items():
                    if field_name in row:
                        if row[field_name] not in value_list:
                            include_row = False
                            break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results

        # Apply not_filters (inequality filters) by filtering in Python
        if not_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value in not_filters.items():
                    if field_name in row and row[field_name] == value:
                        include_row = False
                        break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results
        
        if results:
            # Apply ordering if specified before picking the first
            order_by_field = getattr(self, 'order_by_field', None)
            order_by_desc = getattr(self, 'order_by_desc', False)
            if order_by_field:
                results.sort(key=lambda x: x.get(order_by_field) if x.get(order_by_field) is not None else "", reverse=order_by_desc)

            # Create model instance and populate with data
            instance = self.model_class()
            for key, value in results[0].items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            return instance
        return None

    def all(self):
        # Get all records with filters
        filters = getattr(self, 'filters', {})
        not_filters = getattr(self, 'not_filters', {})
        in_filters = getattr(self, 'in_filters', {})

        # Apply filters to get initial results
        results = supabase_db.get_all(self.table_name, filters)
        
        # Apply in_filters (IN operations) by filtering in Python
        if in_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value_list in in_filters.items():
                    if field_name in row:
                        if row[field_name] not in value_list:
                            include_row = False
                            break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results

        # Apply not_filters (inequality filters) by filtering in Python
        if not_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value in not_filters.items():
                    if field_name in row and row[field_name] == value:
                        include_row = False
                        break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results

        # Apply ordering if specified
        order_by_field = getattr(self, 'order_by_field', None)
        order_by_desc = getattr(self, 'order_by_desc', False)
        if order_by_field:
            # Handle cases where the field might be missing in some rows
            results.sort(key=lambda x: x.get(order_by_field) if x.get(order_by_field) is not None else "", reverse=order_by_desc)

        # Convert results to model instances
        model_results = []
        for row in results:
            instance = self.model_class()
            for key, value in row.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            model_results.append(instance)

        return model_results


    def get(self, id):
        # Get a specific record by ID
        result = supabase_db.get(self.table_name, id)
        if result:
            instance = self.model_class()
            for key, value in result.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            return instance
        return None

    def count(self):
        # Count records with filters applied
        filters = getattr(self, 'filters', {})
        not_filters = getattr(self, 'not_filters', {})
        in_filters = getattr(self, 'in_filters', {})

        # Get all records with filters
        results = supabase_db.get_all(self.table_name, filters)

        # Apply in_filters (IN operations) by filtering in Python
        if in_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value_list in in_filters.items():
                    if field_name in row:
                        if row[field_name] not in value_list:
                            include_row = False
                            break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results

        # Apply not_filters (inequality filters) by filtering in Python
        if not_filters:
            filtered_results = []
            for row in results:
                include_row = True
                for field_name, value in not_filters.items():
                    if field_name in row and row[field_name] == value:
                        include_row = False
                        break
                if include_row:
                    filtered_results.append(row)
            results = filtered_results

        # Note: Ordering doesn't affect count, so we don't apply it here
        return len(results)


class SupabaseSession:
    """
    A session-like class that mimics SQLAlchemy session behavior
    but uses Supabase as the backend
    """

    def __init__(self):
        self.db = supabase_db
        self._flushed_objects = []
        self._deleted_objects = []

    def add(self, obj):
        """
        Add an object to be inserted. This would normally queue for insertion
        but in our implementation, we'll insert immediately to maintain compatibility
        """
        # Extract table name from the object's class
        table_name = getattr(obj.__class__, '__tablename__', obj.__class__.__name__.lower())

        # Convert object to dictionary
        data = self._obj_to_dict(obj)

        # Remove the 'id' field if it's None or 0, so the DB can auto-generate it
        if 'id' in data and (data['id'] is None or data['id'] == 0):
            del data['id']

        result = self.db.insert(table_name, data)

        # Update the object with all returned values from the database
        # This includes fields that were set by database defaults (like upload_date)
        if result:
            for key, value in result.items():
                if hasattr(obj, key):
                    # Handle datetime values that come from the database
                    if isinstance(value, str) and key.endswith('_date'):
                        # If it's a date/time string, we can leave it as is
                        setattr(obj, key, value)
                    else:
                        setattr(obj, key, value)

        self._flushed_objects.append(obj)

    def merge(self, obj):
        """
        Merge an object with the database (insert if new, update if exists)
        """
        table_name = getattr(obj.__class__, '__tablename__', obj.__class__.__name__.lower())

        # Convert object to dictionary
        data = self._obj_to_dict(obj)

        if hasattr(obj, 'id') and obj.id:
            # Update existing record
            result = self.db.update(table_name, obj.id, data)
            if result:
                self._update_obj_from_dict(obj, result)
            return obj
        else:
            # Insert new record
            # Remove the 'id' field if it exists but is None/0
            if 'id' in data and (data['id'] is None or data['id'] == 0):
                del data['id']

            result = self.db.insert(table_name, data)
            if result:
                obj.id = result.get('id')
                self._update_obj_from_dict(obj, result)
            return obj

    def delete(self, obj):
        """
        Delete an object
        """
        if hasattr(obj, 'id') and obj.id:
            table_name = getattr(obj.__class__, '__tablename__', obj.__class__.__name__.lower())
            result = self.db.delete(table_name, obj.id)
            self._deleted_objects.append(obj)
            return result
        return None

    def commit(self):
        """
        Commit all pending changes (in our implementation, operations are immediate)
        """
        # In a real implementation, this would commit all queued operations
        # For now, we just clear the queues since operations are immediate
        self._flushed_objects.clear()
        self._deleted_objects.clear()

    def rollback(self):
        """
        Rollback changes (not implemented in this basic version)
        """
        # In a real implementation, this would revert all queued operations
        self._flushed_objects.clear()
        self._deleted_objects.clear()

    def close(self):
        """
        Close the session
        """
        self.rollback()

    def query_model(self, model_class: Type[T]) -> 'SupabaseQuery':
        """
        Query a specific model class
        """
        table_name = getattr(model_class, '__tablename__', model_class.__name__.lower())
        return SupabaseQuery(self.db, table_name, model_class)

    def _obj_to_dict(self, obj):
        """
        Convert an object to a dictionary representation
        """
        import json
        from datetime import datetime, date
        from decimal import Decimal

        # Define attributes to explicitly exclude from serialization
        exclude_attrs = {'query', 'metadata', 'registry', '_sa_instance_state', '__table__', '_sa_registry',
                         '_decl_class_registry', 'product'}  # Exclude relationship attributes

        # Define known column names for common models to avoid relationship attributes
        # This is a more reliable approach than trying to detect relationships dynamically
        known_columns = {
            'ProductArtwork': ['id', 'product_id', 'filename', 'original_filename', 'file_path', 'file_size', 'mime_type', 'upload_date'],
            'Product': ['id', 'nome', 'sku', 'descricao', 'categoria_id', 'tags', 'preco_custo', 'preco_venda',
                       'estoque_minimo', 'estoque_maximo', 'tipo_material', 'unidade_medida_id', 'sku_pai',
                       'atributos', 'precificacao', 'dados_estoque', 'created_at', 'updated_at']
        }

        # Get the class name to determine which columns to include
        class_name = obj.__class__.__name__
        if class_name in known_columns:
            # Only include known column attributes for this model
            result = {}
            for attr_name in known_columns[class_name]:
                if hasattr(obj, attr_name):
                    attr_value = getattr(obj, attr_name)

                    # For datetime objects, convert them before checking
                    if isinstance(attr_value, (datetime, date)):
                        result[attr_name] = attr_value.isoformat()
                    elif isinstance(attr_value, Decimal):
                        result[attr_name] = float(attr_value)
                    else:
                        try:
                            # Test if the value can be serialized to JSON
                            json.dumps(attr_value, default=str)
                            result[attr_name] = attr_value
                        except (TypeError, ValueError, AttributeError):
                            # If not serializable, skip this attribute
                            print(f"Skipping non-serializable attribute: {attr_name} with type {type(attr_value)}")
                            continue
        else:
            # Fallback to the previous approach for unknown models
            result = {}
            for attr_name in dir(obj):
                # Skip private attributes and known problematic attributes
                if not attr_name.startswith('_') and attr_name not in exclude_attrs:
                    try:
                        attr_value = getattr(obj, attr_name)

                        # Skip if it's a method or property that causes issues
                        if not callable(attr_value) and attr_name not in exclude_attrs:
                            # Skip SQLAlchemy relationship objects and non-serializable attributes
                            if (not hasattr(attr_value, '_sa_instance_state') and
                                not hasattr(attr_value, '__table__') and  # Skip mapped class objects
                                not hasattr(attr_value, '_sa_registry') and  # Skip other SQLAlchemy metadata
                                not hasattr(attr_value, '_decl_class_registry') and  # Another type of registry
                                attr_name not in exclude_attrs):  # Explicitly skip problematic attributes

                                # Check if this is a SQLAlchemy relationship attribute
                                # Relationships often have '_sa_adapter', 'impl', or similar attributes
                                if (hasattr(attr_value, '_sa_adapter') or
                                    hasattr(attr_value, 'impl') or
                                    (hasattr(attr_value, '__class__') and
                                     'InstrumentedAttribute' in str(type(attr_value)))):
                                    # This is a relationship attribute, skip it
                                    continue
                                
                                # Check if this is a MockColumn object (from MockSQLAlchemy)
                                if hasattr(attr_value, '__class__') and attr_value.__class__.__name__ in ('Column', 'MockColumn'):
                                     continue
                                
                                # Also check if it looks like a column definition (has column_type etc)
                                if hasattr(attr_value, 'column_type') and hasattr(attr_value, 'primary_key'):
                                     continue

                                # Check if the value is JSON serializable
                                # For datetime objects, convert them before checking
                                if isinstance(attr_value, (datetime, date)):
                                    result[attr_name] = attr_value.isoformat()
                                elif isinstance(attr_value, Decimal):
                                    result[attr_name] = float(attr_value)
                                else:
                                    try:
                                        # Test if the value can be serialized to JSON
                                        json.dumps(attr_value, default=str)
                                        result[attr_name] = attr_value
                                    except (TypeError, ValueError, AttributeError):
                                        # If not serializable, skip this attribute
                                        print(f"Skipping non-serializable attribute: {attr_name} with type {type(attr_value)}")
                                        continue
                    except AttributeError:
                        # If we can't get the attribute, skip it
                        continue

        return result

    def _update_obj_from_dict(self, obj, data_dict):
        """
        Update an object's attributes from a dictionary
        """
        for key, value in data_dict.items():
            if hasattr(obj, key):
                setattr(obj, key, value)


class SupabaseQuery:
    """
    A query builder that mimics SQLAlchemy's query interface
    """

    def __init__(self, db_service: SupabaseDBService, table_name: str, model_class: Type[T]):
        self.db_service = db_service
        self.table_name = table_name
        self.model_class = model_class
        self.filters = {}
        self.limit_val = None
        self.offset_val = None
        self.order_by_field = None
        self.order_by_desc = False

    def filter_by(self, **kwargs):
        """
        Add filters to the query
        """
        self.filters.update(kwargs)
        return self

    def filter(self, condition):
        """
        Add a filter condition - simplified implementation
        In a real implementation, this would parse SQLAlchemy conditions
        """
        # For now, we'll just pass through the condition as a filter
        # This is a simplified version - a full implementation would parse SQLAlchemy expressions
        if hasattr(condition, 'left') and hasattr(condition, 'right'):
            # This is a basic assumption about SQLAlchemy conditions
            field_name = str(condition.left).split('.')[-1]
            value = condition.right.value if hasattr(condition.right, 'value') else condition.right
            self.filters[field_name] = value

        return self

    def limit(self, limit: int):
        """
        Limit the number of results
        """
        self.limit_val = limit
        return self

    def offset(self, offset: int):
        """
        Offset the results
        """
        self.offset_val = offset
        return self

    def order_by(self, field):
        """
        Order the results by a field
        """
        field_str = str(field)
        if field_str.startswith('-'):  # Assuming negative means descending
            self.order_by_field = field_str[1:]
            self.order_by_desc = True
        else:
            self.order_by_field = field_str
            self.order_by_desc = False
        return self

    def first(self):
        """
        Get the first result
        """
        results = self.limit(1).all()
        return results[0] if results else None

    def all(self):
        """
        Get all results
        """
        # Build the query
        query = self.db_service.client.table(self.table_name).select("*")

        # Apply filters
        for key, value in self.filters.items():
            query = query.eq(key, value)

        # Apply ordering
        if self.order_by_field:
            query = query.order(self.order_by_field, desc=self.order_by_desc)

        # Apply limit and offset
        if self.limit_val:
            query = query.limit(self.limit_val)
        if self.offset_val:
            query = query.range(self.offset_val, self.offset_val + (self.limit_val or 1000))

        response = self.db_service.execute_with_retry(query)

        # Convert results to model instances
        results = []
        for row in response.data:
            instance = self.model_class()
            for key, value in row.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            results.append(instance)

        return results


@contextmanager
def get_db_session():
    """
    Context manager that provides a database session
    """
    session = SupabaseSession()
    try:
        yield session
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    """
    Get a database session (for compatibility with existing code)
    """
    return SupabaseSession()


# Define a mock SQLAlchemy instance to satisfy model requirements
class MockSQLAlchemy:
    """
    A mock SQLAlchemy class to allow models to inherit from db.Model
    without causing runtime errors when using Supabase mode
    """

    class Model:
        """
        A mock Model class that allows models to define columns
        while using Supabase as the backend
        """
        query = None  # Will be set dynamically

        def __init__(self):
            # Initialize with default values
            for attr_name in dir(self.__class__):
                attr_value = getattr(self.__class__, attr_name)
                if hasattr(attr_value, '__class__') and attr_value.__class__.__name__ == 'MockColumn':
                    setattr(self, attr_name, attr_value.default)

    class Column:
        """
        A mock Column class to allow model definitions
        """
        def __init__(self, column_type, primary_key=False, nullable=True, default=None, unique=False, foreign_key=None):
            self.column_type = column_type
            self.primary_key = primary_key
            self.nullable = nullable
            self.default = default
            self.unique = unique
            self.foreign_key = foreign_key

    class Integer:
        def __init__(self):
            pass

    class String:
        def __init__(self, length):
            self.length = length

    class Boolean:
        def __init__(self):
            pass

    class DateTime:
        def __init__(self):
            pass

    class Text:
        def __init__(self):
            pass

    class ForeignKey:
        def __init__(self, table_column):
            self.table_column = table_column


# Create a mock db instance for Supabase mode
mock_db = MockSQLAlchemy()


def init_app_with_supabase_db(app):
    """
    Initialize a Flask app with Supabase database support
    """
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')
    
    if supabase_url and supabase_key:
        # Use Supabase (PostgreSQL) - convert http/https to postgresql protocol
        # Supabase connection string usually starts with postgres:// or postgresql://
        # but we also accept SUPABASE_URL format for simple configuration
        if supabase_url.startswith('http'):
            db_url = supabase_url.replace("http://", "postgresql://").replace("https://", "postgresql://")
        else:
            db_url = supabase_url
            
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
        app.logger.info("Configured Flask app to use Supabase (PostgreSQL) as main database.")
        
        # Test connection optionally
        try:
             # Just ensures supabase_db global is initialized
             if supabase_db._ensure_client():
                 app.logger.info("Supabase client initialized successfully.")
        except Exception as e:
             app.logger.error(f"Failed to initialize Supabase client: {e}")

class DatabaseMode(Enum):
    SUPABASE = "supabase"
    MYSQL = "mysql"

def get_current_database_mode() -> DatabaseMode:
    """
    Returns the current database mode: SUPABASE or MYSQL
    """
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')
    
    if supabase_url and supabase_key:
        return DatabaseMode.SUPABASE
    return DatabaseMode.MYSQL
