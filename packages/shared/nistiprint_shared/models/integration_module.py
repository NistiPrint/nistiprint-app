"""
Data model for integration modules in the marketplace
"""
from datetime import datetime
from typing import Dict, List, Optional


class IntegrationModule:
    """
    Represents an integration module available in the marketplace
    """
    def __init__(
        self,
        id: str = None,
        name: str = "",
        description: str = "",
        version: str = "1.0.0",
        author: str = "",
        icon_url: str = "",
        category: str = "",
        tags: List[str] = None,
        is_active: bool = True,
        config_schema: Dict = None,
        auth_flow: str = "oauth2",  # "oauth2", "api_key", "basic_auth", etc.
        auth_config: Dict = None,
        data_mapping_spec: Dict = None,
        created_at: datetime = None,
        updated_at: datetime = None
    ):
        self.id = id
        self.name = name
        self.description = description
        self.version = version
        self.author = author
        self.icon_url = icon_url
        self.category = category
        self.tags = tags or []
        self.is_active = is_active
        self.config_schema = config_schema or {}
        self.auth_flow = auth_flow
        self.auth_config = auth_config or {}
        self.data_mapping_spec = data_mapping_spec or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """Convert to dictionary for Firestore storage"""
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'author': self.author,
            'icon_url': self.icon_url,
            'category': self.category,
            'tags': self.tags,
            'is_active': self.is_active,
            'config_schema': self.config_schema,
            'auth_flow': self.auth_flow,
            'auth_config': self.auth_config,
            'data_mapping_spec': self.data_mapping_spec,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @classmethod
    def from_dict(cls, data: Dict, module_id: str = None):
        """Create instance from dictionary"""
        from datetime import datetime

        def parse_datetime(dt_value):
            if isinstance(dt_value, datetime):
                return dt_value
            elif isinstance(dt_value, str):
                try:
                    return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
                except ValueError:
                    return datetime.utcnow()
            else:
                return datetime.utcnow()

        return cls(
            id=module_id,
            name=data.get('name', ''),
            description=data.get('description', ''),
            version=data.get('version', '1.0.0'),
            author=data.get('author', ''),
            icon_url=data.get('icon_url', ''),
            category=data.get('category', ''),
            tags=data.get('tags', []),
            is_active=data.get('is_active', True),
            config_schema=data.get('config_schema', {}),
            auth_flow=data.get('auth_flow', 'oauth2'),
            auth_config=data.get('auth_config', {}),
            data_mapping_spec=data.get('data_mapping_spec', {}),
            created_at=parse_datetime(data.get('created_at')) if data.get('created_at') else datetime.utcnow(),
            updated_at=parse_datetime(data.get('updated_at')) if data.get('updated_at') else datetime.utcnow()
        )


class InstalledIntegration:
    """
    Represents an installed instance of an integration module
    """
    def __init__(
        self,
        id: str = None,
        module_id: str = "",
        instance_name: str = "",
        user_id: str = "",  # ID of user who installed
        config: Dict = None,
        credentials: Dict = None,
        access_token: str = None,
        refresh_token: str = None,
        expires_at: datetime = None,
        is_active: bool = True,
        installation_date: datetime = None,
        last_sync: datetime = None,
        sync_status: str = "pending",  # "pending", "success", "error"
        created_at: datetime = None,
        updated_at: datetime = None
    ):
        self.id = id
        self.module_id = module_id
        self.instance_name = instance_name
        self.user_id = user_id
        self.config = config or {}
        self.credentials = credentials or {}
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.is_active = is_active
        self.installation_date = installation_date or datetime.utcnow()
        self.last_sync = last_sync
        self.sync_status = sync_status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """Convert to dictionary for Firestore storage"""
        return {
            'module_id': self.module_id,
            'instance_name': self.instance_name,
            'user_id': self.user_id,
            'config': self.config,
            'credentials': self.credentials,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active,
            # 'installation_date': self.installation_date, # Removed to use created_at
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'sync_status': self.sync_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @classmethod
    def from_dict(cls, data: Dict, instance_id: str = None):
        """Create instance from dictionary"""
        from datetime import datetime

        def parse_datetime(dt_value):
            if isinstance(dt_value, datetime):
                return dt_value
            elif isinstance(dt_value, str):
                try:
                    return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
                except ValueError:
                    return datetime.utcnow()
            else:
                return datetime.utcnow()

        # Map installation_date to created_at if not present
        created_at = parse_datetime(data.get('created_at')) if data.get('created_at') else datetime.utcnow()
        installation_date = parse_datetime(data.get('installation_date')) if data.get('installation_date') else created_at

        return cls(
            id=instance_id,
            module_id=data.get('module_id', ''),
            instance_name=data.get('instance_name', ''),
            user_id=data.get('user_id', ''),
            config=data.get('config', {}),
            credentials=data.get('credentials', {}),
            access_token=data.get('access_token'),
            refresh_token=data.get('refresh_token'),
            expires_at=parse_datetime(data.get('expires_at')) if data.get('expires_at') else None,
            is_active=data.get('is_active', True),
            installation_date=installation_date,
            last_sync=parse_datetime(data.get('last_sync')) if data.get('last_sync') else None,
            sync_status=data.get('sync_status', 'pending'),
            created_at=created_at,
            updated_at=parse_datetime(data.get('updated_at')) if data.get('updated_at') else datetime.utcnow()
        )
