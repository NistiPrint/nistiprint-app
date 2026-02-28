from nistiprint_shared.database.database import db
from datetime import datetime

class BlingPedidoItens(db.Model):
    __tablename__ = 'itens_pedido_bling'

    id = db.Column(db.Integer, primary_key=True)
    pedido_bling_id = db.Column(db.Integer, db.ForeignKey('pedidos_bling.id'), nullable=False)
    codigo = db.Column(db.String(100))
    unidade = db.Column(db.String(20))
    quantidade = db.Column(db.Integer, default=1)
    valor = db.Column(db.Float)
    descricao = db.Column(db.String(500))
    personalizado = db.Column(db.Boolean, default=False)
    produto = db.Column(db.Text)  # JSON string para dados do produto
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)



    def __repr__(self):
        return f'<BlingPedidoItens {self.descricao}>'
