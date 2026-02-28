from nistiprint_shared.database.database import db
from datetime import datetime

class Categoria(db.Model):
    __tablename__ = 'categorias'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.Text)
    parent_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    nivel = db.Column(db.Integer, default=0)  # For hierarchical categories
    path = db.Column(db.Text)  # Full path for easy querying
    ativo = db.Column(db.Boolean, default=True)
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
            'parent_id': self.parent_id,
            'nivel': self.nivel,
            'path': self.path,
            'ativo': self.ativo,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
Categoria.parent = db.relationship('Categoria', remote_side=[Categoria.id], backref='subcategorias')
