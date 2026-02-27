from ..database.database import db
from datetime import datetime

class DemandaItemOrigem(db.Model):
    __tablename__ = 'demandas_item_origem'

    id = db.Column(db.Integer, primary_key=True)
    demanda_item_id = db.Column(db.Integer, db.ForeignKey('itens_demanda.id'), nullable=False)
    plataforma = db.Column(db.String(50), nullable=False)  # Origin platform
    pedido_externo_id = db.Column(db.String(255), nullable=False)  # Order ID on the platform (e.g., Shopee Order SN)
    item_externo_id = db.Column(db.String(255))  # Unique item ID on the platform, if exists, or SKU + Index
    sku_externo = db.Column(db.String(255), nullable=False)  # SKU as received from the platform
    quantidade_atendida = db.Column(db.Integer, nullable=False)  # How much of this external item was absorbed by this demand
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

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
            'demanda_item_id': self.demanda_item_id,
            'plataforma': self.plataforma,
            'pedido_externo_id': self.pedido_externo_id,
            'item_externo_id': self.item_externo_id,
            'sku_externo': self.sku_externo,
            'quantidade_atendida': self.quantidade_atendida,
            'created_at': format_datetime(self.created_at)
        }

# --- Relationships definitions at the bottom ---
DemandaItemOrigem.demanda_item = db.relationship('DemandaProducaoItem', backref='origens')