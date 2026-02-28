from nistiprint_shared.database.database import db
from datetime import datetime

class RecursoProdutivo(db.Model):
    __tablename__ = 'recursos_produtivos'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    tipo = db.Column(db.String(50))  # maquina, equipe, posto_trabalho
    descricao = db.Column(db.Text)
    capacidade = db.Column(db.JSON)  # Capacity specifications
    status = db.Column(db.String(50), default='ATIVO')
    dados_tecnicos = db.Column(db.JSON)  # Technical specifications
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
            'tipo': self.tipo,
            'descricao': self.descricao,
            'capacidade': self.capacidade,
            'status': self.status,
            'dados_tecnicos': self.dados_tecnicos,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
