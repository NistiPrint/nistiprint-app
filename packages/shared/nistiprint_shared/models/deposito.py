from nistiprint_shared.database.database import db
from datetime import datetime

class Deposito(db.Model):
    __tablename__ = 'depositos'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.Text)
    endereco = db.Column(db.JSON)  # Address information
    capacidade = db.Column(db.Numeric(15, 2))
    capacidade_utilizada = db.Column(db.Numeric(15, 2), default=0)
    tipo = db.Column(db.String(50))  # e.g., raw_materials, finished_goods
    ativo = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
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
            'endereco': self.endereco,
            'capacidade': float(self.capacidade) if self.capacidade else None,
            'capacidade_utilizada': float(self.capacidade_utilizada) if self.capacidade_utilizada else None,
            'tipo': self.tipo,
            'ativo': self.ativo,
            'is_default': self.is_default,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
