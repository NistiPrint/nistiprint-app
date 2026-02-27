from ..database.database import db
from datetime import datetime

class Venda(db.Model):
    __tablename__ = 'vendas'

    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.String(255), nullable=False, unique=True)  # Original Firestore document ID
    plataforma = db.Column(db.String(100))  # Platform where sale originated
    status = db.Column(db.String(50))
    total_amount = db.Column(db.Numeric(10, 2))
    currency = db.Column(db.String(10))
    cliente_info = db.Column(db.JSON)  # Customer information
    endereco_entrega = db.Column(db.JSON)  # Delivery address
    itens = db.Column(db.JSON)  # Sale items (could be normalized later)
    data_venda = db.Column(db.DateTime)
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
            'venda_id': self.venda_id,
            'plataforma': self.plataforma,
            'status': self.status,
            'total_amount': float(self.total_amount) if self.total_amount else None,
            'currency': self.currency,
            'cliente_info': self.cliente_info,
            'endereco_entrega': self.endereco_entrega,
            'itens': self.itens,
            'data_venda': format_datetime(self.data_venda),
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }