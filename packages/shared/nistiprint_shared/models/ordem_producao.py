from nistiprint_shared.database.database import db
from datetime import datetime

class OrdemProducao(db.Model):
    __tablename__ = 'ordens_producao'

    id = db.Column(db.Integer, primary_key=True)
    ordem_id = db.Column(db.String(255), nullable=False, unique=True)  # Original Firestore document ID
    numero_ordem = db.Column(db.String(100), unique=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)  # products → produtos
    sku = db.Column(db.String(100))
    descricao = db.Column(db.Text)
    quantidade = db.Column(db.Integer)
    status = db.Column(db.String(50), default='PENDENTE')
    data_inicio = db.Column(db.Date)
    data_fim = db.Column(db.Date)
    prioridade = db.Column(db.Integer, default=0)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    dados_adicionais = db.Column(db.JSON)  # Additional production data
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
            'ordem_id': self.ordem_id,
            'numero_ordem': self.numero_ordem,
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,  # name → nome
            'sku': self.sku,
            'descricao': self.descricao,
            'quantidade': self.quantidade,
            'status': self.status,
            'data_inicio': self.data_inicio.isoformat() if self.data_inicio else None,
            'data_fim': self.data_fim.isoformat() if self.data_fim else None,
            'prioridade': self.prioridade,
            'responsavel_id': self.responsavel_id,
            'responsavel_nome': self.responsavel.nome if self.responsavel else None,
            'dados_adicionais': self.dados_adicionais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
OrdemProducao.produto = db.relationship('Product', backref='ordens_producao')
OrdemProducao.responsavel = db.relationship('Usuario', backref='ordens_producao_responsavel')
