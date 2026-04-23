from services.database.database import db
from datetime import datetime

class BlingPedidos(db.Model):
    __tablename__ = 'bling_pedidos'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50), nullable=False)
    numeroLoja = db.Column(db.String(100))
    data = db.Column(db.DateTime, nullable=False)
    contato = db.Column(db.Text)
    personalizado = db.Column(db.Boolean, default=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    bling_id = db.Column(db.BigInteger, nullable=False)
    deletado = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<BlingPedidos {self.numero}>'
