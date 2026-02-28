from nistiprint_shared.database.database import db
from datetime import datetime

class InstalledIntegration(db.Model):
    __tablename__ = 'installed_integrations'

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.String(100), nullable=False)  # shopee, mercadolivre, amazon, shein
    instance_name = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.String(255))
    
    # Configurações da plataforma (shop_id, region, etc)
    config = db.Column(db.JSON, default={})
    
    # Credenciais e Tokens
    access_token = db.Column(db.Text)
    refresh_token = db.Column(db.Text)
    expires_at = db.Column(db.DateTime)
    
    is_active = db.Column(db.Boolean, default=True)
    last_sync = db.Column(db.DateTime)
    sync_status = db.Column(db.String(50), default='pending')
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'module_id': self.module_id,
            'instance_name': self.instance_name,
            'user_id': self.user_id,
            'config': self.config,
            'is_active': self.is_active,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'sync_status': self.sync_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
