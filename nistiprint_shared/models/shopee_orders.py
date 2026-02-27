import json
from datetime import datetime
from ..database.database import db

class ShopeeOrders(db.Model):
    __tablename__ = 'pedidos_shopee'  # shopee_orders → pedidos_shopee

    id = db.Column(db.Integer, primary_key=True)  # Novo campo ID auto-increment
    codigo_pedido = db.Column(db.String(255), nullable=False, unique=True)  # order_sn → codigo_pedido
    id_pedido_shopee = db.Column(db.BigInteger, unique=True, nullable=True)  # order_id → id_pedido_shopee
    status_pedido = db.Column(db.String(100))  # Novo campo
    valor_total = db.Column(db.Numeric(10, 2))  # Novo campo
    moeda = db.Column(db.String(10))  # Novo campo
    data_criacao = db.Column(db.DateTime)  # Novo campo
    data_atualizacao = db.Column(db.DateTime)  # Novo campo
    data_pagamento = db.Column(db.DateTime)  # Novo campo
    dias_para_envio = db.Column(db.Integer)  # Novo campo
    data_envio = db.Column(db.DateTime)  # Novo campo
    endereco_entrega = db.Column(db.JSON)  # Novo campo
    itens_pedido = db.Column(db.JSON)  # Novo campo
    informacoes_comprador = db.Column(db.JSON)  # buyer_info → informacoes_comprador
    mensagem = db.Column(db.Text)  # Mantido
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def username(self):
        try:
            if self.informacoes_comprador:  # buyer_info → informacoes_comprador
                buyer_data = json.loads(self.informacoes_comprador)
                return buyer_data.get('username')
            return 'n/a'
        except (json.JSONDecodeError, AttributeError):
            return 'n/a'
