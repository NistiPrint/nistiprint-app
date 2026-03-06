from nistiprint_shared.database.database import db
from datetime import datetime

class Fornecedor(db.Model):
    __tablename__ = 'fornecedores'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    cnpj = db.Column(db.String(20))
    contato_principal = db.Column(db.Text)
    informacoes_contato = db.Column(db.JSON)  # Phone, email, address
    categoria = db.Column(db.String(100))  # Raw materials, services, etc.
    classificacao = db.Column(db.Integer)  # Rating (1-5)
    ativo = db.Column(db.Boolean, default=True)
    dados_contratuais = db.Column(db.JSON)  # Contractual information
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
            'cnpj': self.cnpj,
            'contato_principal': self.contato_principal,
            'informacoes_contato': self.informacoes_contato,
            'categoria': self.categoria,
            'classificacao': self.classificacao,
            'ativo': self.ativo,
            'dados_contratuais': self.dados_contratuais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
