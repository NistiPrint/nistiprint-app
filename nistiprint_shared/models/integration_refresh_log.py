from nistiprint_shared.database.database import db
from datetime import datetime

class IntegrationRefreshLog(db.Model):
    __tablename__ = 'integration_refresh_logs'

    id = db.Column(db.Integer, primary_key=True)
    integration_id = db.Column(db.Integer, db.ForeignKey('installed_integrations.id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)  # success, error, skipped
    message = db.Column(db.Text)
    execution_mode = db.Column(db.String(50), default='scheduled')  # manual, scheduled
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relacionamento
    integration = db.relationship('InstalledIntegration', backref=db.backref('refresh_logs', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'integration_id': self.integration_id,
            'status': self.status,
            'message': self.message,
            'execution_mode': self.execution_mode,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
