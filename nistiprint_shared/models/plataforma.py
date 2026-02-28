from nistiprint_shared.database.database import db
from datetime import datetime

class Plataforma(db.Model):
    __tablename__ = 'plataformas'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.Text)
    tipo = db.Column(db.String(50))  # e.g., ecommerce, marketplace
    ativa = db.Column(db.Boolean, default=True)
    configuracao = db.Column(db.JSON)  # Platform-specific configuration
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def format_datetime(dt):
            if dt is None:
                return None
            elif isinstance(dt, str):
                return dt  # Already a string from Supabase
            else:
                return dt.isoformat()  # Convert datetime object to string

        return {
            'id': self.id,
            'nome': self.nome,
            'descricao': self.descricao,
            'tipo': self.tipo,
            'ativa': self.ativa,
            'configuracao': self.configuracao,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
