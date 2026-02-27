from ..database.database import db
from datetime import datetime

class WebhookLog(db.Model):
    __tablename__ = 'webhook_logs'

    id = db.Column(db.Integer, primary_key=True)
    plataforma = db.Column(db.String(50), nullable=False)  # shopee, mercadolivre, etc.
    instance_id = db.Column(db.String(255))  # ID da integração instalada
    evento = db.Column(db.String(100))  # tipo de evento (order_update, etc)
    payload = db.Column(db.JSON, nullable=False)
    headers = db.Column(db.JSON)
    status = db.Column(db.String(20), default='PENDENTE')  # PENDENTE, PROCESSADO, ERRO
    mensagem_erro = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'plataforma': self.plataforma,
            'instance_id': self.instance_id,
            'evento': self.evento,
            'payload': self.payload,
            'headers': self.headers,
            'status': self.status,
            'mensagem_erro': self.mensagem_erro,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None
        }
