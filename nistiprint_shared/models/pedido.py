from ..database.database import db
from datetime import datetime
import uuid

class Pedido(db.Model):
    __tablename__ = 'pedidos'

    id = db.Column(db.Integer, primary_key=True)
    uuid_pedido = db.Column(db.String(36), default=lambda: str(uuid.uuid4()), unique=True, nullable=False)  # ID universal único
    numero_pedido = db.Column(db.String(50), nullable=False, unique=True)  # ID amigável ou gerado
    pedido_externo_id = db.Column(db.String(100))  # ID na Shopee/Bling
    origem = db.Column(db.String(50), nullable=False)  # 'SHOPEE', 'BLING', 'MANUAL'
    informacoes_cliente = db.Column(db.JSON, nullable=False)  # Desnormalizado para performance
    situacao_pedido_id = db.Column(db.Integer, db.ForeignKey('situacoes_pedido.id'))
    valor_total = db.Column(db.Numeric(15, 2))
    moeda = db.Column(db.String(10), default='BRL')
    data_pedido = db.Column(db.DateTime, default=datetime.utcnow)
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
            'uuid_pedido': self.uuid_pedido,
            'numero_pedido': self.numero_pedido,
            'pedido_externo_id': self.pedido_externo_id,
            'origem': self.origem,
            'informacoes_cliente': self.informacoes_cliente,
            'situacao_pedido_id': self.situacao_pedido_id,
            'situacao_pedido': self.situacao_pedido.to_dict() if self.situacao_pedido else None,
            'valor_total': float(self.valor_total) if self.valor_total else None,
            'moeda': self.moeda,
            'data_pedido': format_datetime(self.data_pedido),
            'itens': [item.to_dict() for item in self.itens],
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }


class ItemPedido(db.Model):
    __tablename__ = 'itens_pedido'

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'))  # Link com produto local
    sku_externo = db.Column(db.String(100))  # Snapshot do SKU vendido
    descricao = db.Column(db.String(500))
    quantidade = db.Column(db.Numeric(10, 4))
    preco_unitario = db.Column(db.Numeric(15, 2))
    subtotal = db.Column(db.Numeric(15, 2))
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
            'pedido_id': self.pedido_id,
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,
            'sku_externo': self.sku_externo,
            'descricao': self.descricao,
            'quantidade': float(self.quantidade) if self.quantidade else None,
            'preco_unitario': float(self.preco_unitario) if self.preco_unitario else None,
            'subtotal': float(self.subtotal) if self.subtotal else None,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
Pedido.situacao_pedido = db.relationship('SituacaoPedido', backref='pedidos', lazy=True)
Pedido.itens = db.relationship('ItemPedido', backref='pedido', lazy=True, cascade='all, delete-orphan')
ItemPedido.produto = db.relationship('Product', backref='itens_pedido', lazy=True)