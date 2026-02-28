from nistiprint_shared.database.database import db
from datetime import datetime

class FornecedorInsumo(db.Model):
    """
    Tabela de relacionamento entre Fornecedores e Insumos (Produtos).
    Armazena dados logísticos e comerciais específicos para a produção.
    """
    __tablename__ = 'fornecedor_insumos'

    id = db.Column(db.Integer, primary_key=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=False)
    
    # Dados Logísticos
    lead_time_dias = db.Column(db.Integer, default=0)  # Dias entre pedido e entrega
    moq = db.Column(db.Float, default=0.0)  # Minimum Order Quantity (Lote Mínimo)
    unidade_compra = db.Column(db.String(20))  # Ex: 'KG', 'LITRO', 'CAIXA'
    
    # Dados Comerciais
    preco_ultima_compra = db.Column(db.Float)
    moeda = db.Column(db.String(10), default='BRL')
    codigo_no_fornecedor = db.Column(db.String(100))
    
    link_produto_fornecedor = db.Column(db.Text)
    preferencial = db.Column(db.Boolean, default=False)  # Se é o fornecedor principal para este item
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    fornecedor = db.relationship('Fornecedor', backref=db.backref('insumos_fornecidos', lazy='dynamic'))
    produto = db.relationship('Product', backref=db.backref('fornecedores_vinculados', lazy='dynamic'))

    def to_dict(self):
        def format_datetime(dt):
            if dt is None: return None
            if isinstance(dt, str): return dt
            return dt.isoformat()

        return {
            'id': self.id,
            'fornecedor_id': self.fornecedor_id,
            'fornecedor_nome': self.fornecedor.nome if self.fornecedor else None,
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,
            'lead_time_dias': self.lead_time_dias,
            'moq': self.moq,
            'unidade_compra': self.unidade_compra,
            'preco_ultima_compra': self.preco_ultima_compra,
            'moeda': self.moeda,
            'codigo_no_fornecedor': self.codigo_no_fornecedor,
            'link_produto_fornecedor': self.link_produto_fornecedor,
            'preferencial': self.preferencial,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }
