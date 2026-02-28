from nistiprint_shared.database.database import db
from datetime import datetime

class CanalVenda(db.Model):
    __tablename__ = 'canais_venda'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    plataforma_id = db.Column(db.Integer, db.ForeignKey('plataformas.id'), nullable=True)
    descricao = db.Column(db.Text)
    configuracao = db.Column(db.JSON)  # Channel-specific configuration (without logistic rules)
    ativo = db.Column(db.Boolean, default=True)

    # Removido: flags de logística (flex, fulfillment) conforme refatoração
    # As configurações de logística agora são definidas na criação da demanda
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
            'plataforma_id': self.plataforma_id,
            'plataforma_nome': self.plataforma.nome if self.plataforma else None,
            'descricao': self.descricao,
            'configuracao': self.configuracao,
            'ativo': self.ativo,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
CanalVenda.plataforma = db.relationship('Plataforma', backref='canais_venda')
