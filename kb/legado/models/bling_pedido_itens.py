from services.database.database import db
from datetime import datetime

class BlingPedidoItens(db.Model):
    __tablename__ = 'bling_pedido_itens'

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('bling_pedidos.id'), nullable=False)
    codigo = db.Column(db.String(100))
    unidade = db.Column(db.String(20))
    quantidade = db.Column(db.Integer, default=1)
    valor = db.Column(db.Float)
    descricao = db.Column(db.String(500))
    personalizado = db.Column(db.Boolean, default=False)
    produto = db.Column(db.Text)  # JSON string para dados do produto
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    # Relacionamento com o pedido
    pedido = db.relationship('BlingPedidos', backref=db.backref('itens', lazy=True))

    def __repr__(self):
        return f'<BlingPedidoItens {self.descricao}>'
