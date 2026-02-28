from nistiprint_shared.database.database import db
from datetime import datetime

class ProdutoExterno(db.Model):
    __tablename__ = 'produtos_externos'

    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)  # Points to variant or simple product
    codigo_externo = db.Column(db.String(255), nullable=False)  # SKU or ID on the platform
    plataforma = db.Column(db.String(50), nullable=False)  # Platform: 'Bling', 'Shopee', 'MercadoLivre', 'Amazon', 'Shein', etc.
    metadados = db.Column(db.JSON)  # To store extra platform info if needed
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    produto = db.relationship('Product', backref='produtos_externos')

    __table_args__ = (db.UniqueConstraint('plataforma', 'codigo_externo', name='unique_plataforma_codigo_externo'),)

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
            'produto_nome': self.produto.nome if self.produto else None,
            'codigo_externo': self.codigo_externo,
            'plataforma': self.plataforma,
            'metadados': self.metadados,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
