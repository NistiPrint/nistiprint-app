from nistiprint_shared.database.database import db
from datetime import datetime

class EstoqueAtual(db.Model):
    __tablename__ = 'estoque_atual'

    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)  # products → produtos
    deposito_id = db.Column(db.Integer, db.ForeignKey('depositos.id'), nullable=False)
    saldo_atual = db.Column(db.Integer, default=0)
    nivel_minimo = db.Column(db.Integer, default=0)
    nivel_maximo = db.Column(db.Integer)
    reservado = db.Column(db.Integer, default=0)  # Quantity reserved for production
    ultima_atualizacao = db.Column(db.DateTime, default=datetime.utcnow)
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
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,  # name → nome
            'deposito_id': self.deposito_id,
            'deposito_nome': self.deposito.nome if self.deposito else None,
            'saldo_atual': self.saldo_atual,
            'nivel_minimo': self.nivel_minimo,
            'nivel_maximo': self.nivel_maximo,
            'reservado': self.reservado,
            'disponivel': self.saldo_atual - self.reservado,  # Calculate on the fly
            'ultima_atualizacao': format_datetime(self.ultima_atualizacao),
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
EstoqueAtual.produto = db.relationship('Product', backref='estoque_atual')
EstoqueAtual.deposito = db.relationship('Deposito', backref='estoque_atual')
