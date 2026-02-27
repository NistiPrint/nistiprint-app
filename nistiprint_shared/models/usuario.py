from datetime import datetime
from ..database.database import db
from werkzeug.security import generate_password_hash, check_password_hash

class Usuario(db.Model):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    senha_hash = db.Column(db.String(256), nullable=False)
    setor_id = db.Column(db.Integer, db.ForeignKey('setores.id'), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

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
            'email': self.email,
            'setor_id': self.setor_id,
            'setor_nome': self.setor_nome,  # Use the property to ensure consistent access
            'ativo': self.ativo,
            'is_admin': self.is_admin,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at),
            'last_login': format_datetime(self.last_login)
        }

    def to_dict_without_password(self):
        data = self.to_dict()
        # Remove senha_hash do dicionário
        return data

    @property
    def setor_nome(self):
        """Property to access the setor name safely."""
        if self.setor:
            return self.setor.nome
        return None