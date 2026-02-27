from ..database.database import db
from datetime import datetime

class SituacaoPedido(db.Model):
    __tablename__ = 'situacoes_pedido'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)  # Nome identificador do status (ex: "Pendente", "Pago", "Processando", "Enviado", "Cancelado")
    descricao = db.Column(db.Text)  # Descrição detalhada do status
    flag_reserva_estoque = db.Column(db.Boolean, default=False)  # Indica se esta situação requer reserva de estoque
    flag_fatura = db.Column(db.Boolean, default=False)  # Indica se esta situação gera faturamento
    flag_cancelado = db.Column(db.Boolean, default=False)  # Indica se esta situação representa um pedido cancelado
    cor_status = db.Column(db.String(7), default='#007bff')  # Cor para representação visual no frontend
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
            'nome': self.nome,
            'descricao': self.descricao,
            'flag_reserva_estoque': self.flag_reserva_estoque,
            'flag_fatura': self.flag_fatura,
            'flag_cancelado': self.flag_cancelado,
            'cor_status': self.cor_status,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }