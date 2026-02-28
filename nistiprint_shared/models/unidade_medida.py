from nistiprint_shared.database.database import db
from datetime import datetime

class UnidadeMedida(db.Model):
    __tablename__ = 'unidades_medida'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    abreviacao = db.Column(db.String(20))
    descricao = db.Column(db.Text)
    tipo = db.Column(db.String(50))  # e.g., length, weight, volume
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
            'abreviacao': self.abreviacao,
            'descricao': self.descricao,
            'tipo': self.tipo,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
