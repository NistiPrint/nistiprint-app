from ..database.database import db
from datetime import datetime

class OrdemCompra(db.Model):
    __tablename__ = 'ordens_compra'

    id = db.Column(db.Integer, primary_key=True)
    ordem_compra_id = db.Column(db.String(255), nullable=False, unique=True)  # Original Firestore document ID
    numero_ordem = db.Column(db.String(100), unique=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id'), nullable=True)
    status = db.Column(db.String(50), default='PENDENTE')
    data_emissao = db.Column(db.Date)
    data_entrega_prevista = db.Column(db.Date)
    valor_total = db.Column(db.Numeric(10, 2))
    dados_adicionais = db.Column(db.JSON)  # Additional purchase order data
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
            'ordem_compra_id': self.ordem_compra_id,
            'numero_ordem': self.numero_ordem,
            'fornecedor_id': self.fornecedor_id,
            'fornecedor_nome': self.fornecedor.nome if self.fornecedor else None,
            'status': self.status,
            'data_emissao': format_datetime(self.data_emissao),
            'data_entrega_prevista': format_datetime(self.data_entrega_prevista),
            'valor_total': float(self.valor_total) if self.valor_total else None,
            'dados_adicionais': self.dados_adicionais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
OrdemCompra.fornecedor = db.relationship('Fornecedor', backref='ordens_compra')