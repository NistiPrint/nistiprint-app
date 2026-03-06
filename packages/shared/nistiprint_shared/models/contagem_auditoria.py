from nistiprint_shared.database.database import db
from datetime import datetime

class ContagemAuditoria(db.Model):
    __tablename__ = 'contagens_auditoria'

    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    deposito_id = db.Column(db.Integer, db.ForeignKey('depositos.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True) # Quem contou
    
    quantidade_contada = db.Column(db.Float, nullable=False)
    saldo_sistema_snapshot = db.Column(db.Float, nullable=False) # Saldo no momento da contagem
    diferenca = db.Column(db.Float, nullable=False) # contada - snapshot
    
    data_contagem = db.Column(db.DateTime, default=datetime.utcnow)
    
    status = db.Column(db.String(20), default='PENDENTE', nullable=False) # PENDENTE, APROVADO, REJEITADO
    observacao = db.Column(db.Text, nullable=True)
    
    # Controle de Aprovação
    usuario_aprovador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    data_processamento = db.Column(db.DateTime, nullable=True)
    
    sessao_inventario_id = db.Column(db.String(50), nullable=True) # Opcional: Link com sessão de inventário

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    produto = db.relationship('Product', backref='contagens_auditoria')
    deposito = db.relationship('Deposito', backref='contagens_auditoria')
    usuario = db.relationship('Usuario', foreign_keys=[usuario_id], backref='contagens_realizadas')
    usuario_aprovador = db.relationship('Usuario', foreign_keys=[usuario_aprovador_id], backref='contagens_aprovadas')

    def to_dict(self):
        def format_datetime(dt):
            if dt is None:
                return None
            return dt.isoformat()

        return {
            'id': self.id,
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,
            'produto_sku': self.produto.sku if self.produto else None,
            'deposito_id': self.deposito_id,
            'deposito_nome': self.deposito.nome if self.deposito else None,
            'usuario_id': self.usuario_id,
            'usuario_nome': self.usuario.nome if self.usuario else None,
            'quantidade_contada': self.quantidade_contada,
            'saldo_sistema_snapshot': self.saldo_sistema_snapshot,
            'diferenca': self.diferenca,
            'data_contagem': format_datetime(self.data_contagem),
            'status': self.status,
            'observacao': self.observacao,
            'usuario_aprovador_id': self.usuario_aprovador_id,
            'usuario_aprovador_nome': self.usuario_aprovador.nome if self.usuario_aprovador else None,
            'data_processamento': format_datetime(self.data_processamento),
            'sessao_inventario_id': self.sessao_inventario_id,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
