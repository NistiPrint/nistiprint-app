from datetime import datetime
from ..database.database import db

class Recurso(db.Model):
    __tablename__ = 'recursos'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True) # ex: 'vendas', 'producao'
    descricao = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
            'created_at': format_datetime(self.created_at)
        }

class PermissaoSetor(db.Model):
    __tablename__ = 'permissoes_setor'

    id = db.Column(db.Integer, primary_key=True)
    setor_id = db.Column(db.Integer, db.ForeignKey('setores.id'), nullable=False)
    recurso_id = db.Column(db.Integer, db.ForeignKey('recursos.id'), nullable=False)

    pode_ler = db.Column(db.Boolean, default=False, nullable=False)
    pode_criar = db.Column(db.Boolean, default=False, nullable=False)
    pode_editar = db.Column(db.Boolean, default=False, nullable=False)
    pode_excluir = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    setor = db.relationship('Setor', backref=db.backref('permissoes', lazy=True))
    recurso = db.relationship('Recurso', backref=db.backref('permissoes', lazy=True))

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
            'setor_id': self.setor_id,
            'recurso_id': self.recurso_id,
            'recurso_nome': self.recurso.nome if self.recurso else None,
            'pode_ler': self.pode_ler,
            'pode_criar': self.pode_criar,
            'pode_editar': self.pode_editar,
            'pode_excluir': self.pode_excluir,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }