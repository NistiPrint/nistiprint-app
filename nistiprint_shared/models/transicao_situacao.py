from ..database.database import db
from datetime import datetime

class TransicaoSituacao(db.Model):
    __tablename__ = 'transicoes_situacao'

    id = db.Column(db.Integer, primary_key=True)
    situacao_origem_id = db.Column(db.Integer, db.ForeignKey('situacoes_pedido.id'), nullable=False)
    situacao_destino_id = db.Column(db.Integer, db.ForeignKey('situacoes_pedido.id'), nullable=False)
    regra_permissao = db.Column(db.String(100))  # Regra de permissão necessária para a transição (ex: "vendas.editar", "producao.confirmar")
    descricao_transicao = db.Column(db.Text)  # Descrição da ação realizada na transição
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
            'situacao_origem_id': self.situacao_origem_id,
            'situacao_destino_id': self.situacao_destino_id,
            'situacao_origem': self.situacao_origem.to_dict() if self.situacao_origem else None,
            'situacao_destino': self.situacao_destino.to_dict() if self.situacao_destino else None,
            'regra_permissao': self.regra_permissao,
            'descricao_transicao': self.descricao_transicao,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom ---
TransicaoSituacao.situacao_origem = db.relationship('SituacaoPedido', foreign_keys=[TransicaoSituacao.situacao_origem_id], backref='transicoes_saida')
TransicaoSituacao.situacao_destino = db.relationship('SituacaoPedido', foreign_keys=[TransicaoSituacao.situacao_destino_id], backref='transicoes_entrada')