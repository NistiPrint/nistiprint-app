from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

class TagService:
    """Service for managing tags in Supabase."""

    def __init__(self):
        self.table = supabase_db.table('tags')

    def get_all(self):
        """Get all tags."""
        print("DEBUG: TagService.get_all called")
        try:
            # Use 'nome' as per schema, not 'name'
            response = self.table.select("*").order('nome').execute()
            print(f"DEBUG: TagService.get_all retrieved {len(response.data)} records")

            tags = []
            for row in response.data:
                tag = dict(row)
                # Map 'nome' to 'name' for application compatibility
                tag['name'] = row.get('nome')
                tags.append(tag)
            return tags
        except Exception as e:
            print(f"ERROR: TagService.get_all failed: {e}")
            # Don't raise the exception to prevent cascading failures
            # Return an empty list as a fallback
            return []

    def get_by_id(self, tag_id: str):
        """Get tag by ID."""
        try:
            response = self.table.select("*").eq('id', tag_id).execute()
            if response.data:
                tag = dict(response.data[0])
                tag['name'] = tag.get('nome')
                return tag
            return None
        except Exception as e:
            print(f"ERROR: TagService.get_by_id failed: {e}")
            return None

    def get_by_name(self, name: str):
        """Get tag by name."""
        try:
            # Query by 'nome'
            response = self.table.select("*").eq('nome', name).execute()
            if response.data:
                tag = dict(response.data[0])
                tag['name'] = tag.get('nome')
                return tag
            return None
        except Exception as e:
            print(f"ERROR: TagService.get_by_name failed: {e}")
            return None

    def get_products_count(self, tag_id: str):
        """Get the count of products associated with this tag."""
        # This would typically involve joining with a products_tags table
        # For now, we'll return 0 as the association logic may be different
        return 0

    def create(self, tag_data):
        """Create a new tag."""
        print(f"DEBUG: TagService.create called with {tag_data}")
        # Check if tag with same name already exists
        if self.get_by_name(tag_data['name']):
            raise ValueError(f"Tag with name '{tag_data['name']}' already exists")

        data = {
            'nome': tag_data['name'], # Map to 'nome'
            # 'composition_template_id': tag_data.get('composition_template_id'), 
            # NOTE: composition_template_id column missing in tags table schema.
            # Commenting out to prevent error until schema is updated.
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # If schema is updated later, we can uncomment this or use 'attributes' JSONB if added
        if 'composition_template_id' in tag_data:
             print(f"WARNING: composition_template_id provided ({tag_data['composition_template_id']}) but column missing in schema. Ignoring.")

        try:
            response = self.table.insert(data).execute()
            if response.data:
                result = dict(response.data[0])
                result['id'] = result.get('id')
                result['name'] = result.get('nome')
                return result
            return None
        except Exception as e:
            print(f"ERROR: TagService.create failed: {e}")
            raise e

    def update(self, tag_id: str, tag_data):
        """Update an existing tag."""
        print(f"DEBUG: TagService.update called for {tag_id} with {tag_data}")
        # Check if name is being updated and if it conflicts
        if 'name' in tag_data:
            existing = self.get_by_name(tag_data['name'])
            # Compare IDs carefully (str vs int)
            if existing and str(existing['id']) != str(tag_id):
                raise ValueError(f"Tag with name '{tag_data['name']}' already exists")

        update_data = {'updated_at': datetime.utcnow().isoformat()}
        if 'name' in tag_data:
            update_data['nome'] = tag_data['name']
        
        # composition_template_id handling disabled due to missing column
        if 'composition_template_id' in tag_data:
             print(f"WARNING: composition_template_id provided ({tag_data['composition_template_id']}) but column missing in schema. Ignoring.")

        try:
            if update_data:  # Only update if there's data to update
                self.table.update(update_data).eq('id', tag_id).execute()

            # Return updated tag
            return self.get_by_id(tag_id)
        except Exception as e:
            print(f"ERROR: TagService.update failed: {e}")
            raise e

    def delete(self, tag_id: str):
        """Delete a tag."""
        print(f"DEBUG: TagService.delete called for {tag_id}")
        try:
            response = self.table.delete().eq('id', tag_id).execute()
            return len(response.data) > 0
        except Exception as e:
            print(f"ERROR: TagService.delete failed: {e}")
            raise e

# Global instance for use throughout the application
tag_service = TagService()

