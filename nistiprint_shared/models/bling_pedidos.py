from nistiprint_shared.database.database import db
from datetime import datetime

class BlingPedidos(db.Model):
    __tablename__ = 'pedidos_bling'

    id = db.Column(db.Integer, primary_key=True)
    numero_pedido = db.Column(db.String(255), nullable=False, unique=True)  # numero → numero_pedido
    loja_id = db.Column(db.Integer)  # numeroLoja → loja_id (numérico)
    numero_loja = db.Column(db.Text)  # numeroLoja → numero_loja (alfanumérico/SN)
    situacao_pedido = db.Column(db.String(100))  # Novo campo
    data_pedido = db.Column(db.Date)  # data → data_pedido
    valor_total = db.Column(db.Numeric(10, 2))  # Novo campo
    nome_cliente = db.Column(db.String(255))  # Novo campo
    email_cliente = db.Column(db.String(255))  # Novo campo
    telefone_cliente = db.Column(db.String(50))  # Novo campo
    endereco_entrega = db.Column(db.JSON)  # Novo campo
    itens = db.Column(db.JSON)  # Novo campo
    contato = db.Column(db.Text)  # Mantido para compatibilidade
    personalizado = db.Column(db.Boolean, default=False)  # Mantido
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)  # Mantido
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # Mantido
    bling_id = db.Column(db.BigInteger, nullable=False)  # Mantido
    deletado = db.Column(db.Boolean, default=False)  # Mantido

    def __repr__(self):
        return f'<BlingPedidos {self.numero_pedido}>'  # numero → numero_pedido

# --- Relationships definitions at the bottom ---
BlingPedidos.itens_pedido = db.relationship('BlingPedidoItens', backref='pedido', lazy=True, foreign_keys='BlingPedidoItens.pedido_bling_id')
