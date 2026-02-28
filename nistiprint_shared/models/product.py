from nistiprint_shared.database.database import db
from datetime import datetime

class Product(db.Model):
    __tablename__ = 'produtos'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)  # name → nome
    sku = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.Text)  # description → descricao
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)  # category_id → categoria_id
    tags = db.Column(db.ARRAY(db.String), nullable=True)  # Array of tag strings

    # Campos normalizados (migrados de JSON para colunas relacionais)
    preco_custo = db.Column(db.Numeric(10, 4), nullable=True)  # Cost price
    preco_venda = db.Column(db.Numeric(10, 4), nullable=True)  # Sale price
    estoque_minimo = db.Column(db.Integer, nullable=False, default=0)  # Minimum stock
    estoque_maximo = db.Column(db.Integer, nullable=False, default=0)  # Maximum stock
    tipo_material = db.Column(db.String(50), nullable=True)  # Material type
    unidade_medida_id = db.Column(db.Integer, db.ForeignKey('unidades_medida.id'), nullable=True)  # Unit of measure
    status = db.Column(db.String(50), nullable=False, default='ativo')  # Product status (ativo/inativo)
    sku_pai = db.Column(db.String(100), nullable=True)  # Parent SKU for BOM products
    parent_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)  # Parent product ID for variations

    # Novos campos para suporte a variações, composições e kits
    formato = db.Column(db.String(50), nullable=False, default='simples')  # simples, com_variacao, variacao, composicao, kit
    herdar_dados_pai = db.Column(db.Boolean, nullable=False, default=True)  # Se verdadeiro, herda dados do produto pai
    herdar_bom_pai = db.Column(db.Boolean, nullable=False, default=True)  # Se verdadeiro, herda BOM do produto pai

    # Campos para Planejamento de Produção e Estoque Inteligente
    estoque_seguranca_dias = db.Column(db.Integer, default=0)  # Dias de cobertura desejados
    ponto_ressuprimento = db.Column(db.Float)  # Gatilho de compra (calculado ou manual)
    lote_economico = db.Column(db.Float)  # Sugestão de lote de compra
    curva_abc = db.Column(db.String(1), nullable=True)  # A, B ou C

    # Campos JSON mantidos para dados flexíveis/legados
    atributos = db.Column(db.JSON)  # attributes → atributos (Flexible product attributes)
    precificacao = db.Column(db.JSON)  # pricing → precificacao (Complex pricing structures - LEGACY)
    dados_estoque = db.Column(db.JSON)  # inventory_data → dados_estoque (Inventory-related information - LEGACY)

    # Campo para definir setor responsável pelo produto
    setor_responsavel_id = db.Column(db.Integer, db.ForeignKey('setores.id'), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, include_variants=True):
        def format_datetime(dt):
            if dt is None:
                return None
            elif isinstance(dt, str):
                return dt  # Already a string from Supabase
            else:
                return dt.isoformat()  # Convert datetime object to string

        result = {
            'id': self.id,
            'nome': self.nome,  # name → nome
            'sku': self.sku,
            'descricao': self.descricao,  # description → descricao
            'categoria_id': self.categoria_id,  # category_id → categoria_id
            'categoria_nome': self.categoria.nome if self.categoria else None,  # category_name → categoria_nome
            'tags': self.tags,

            # Campos normalizados (novos)
            'preco_custo': float(self.preco_custo) if self.preco_custo else None,
            'preco_venda': float(self.preco_venda) if self.preco_venda else None,
            'estoque_minimo': self.estoque_minimo,
            'estoque_maximo': self.estoque_maximo,
            'tipo_material': self.tipo_material,
            'unidade_medida_id': self.unidade_medida_id,
            'status': self.status,
            'unidade_medida_nome': self.unidade_medida.nome if self.unidade_medida else None,
            'sku_pai': self.sku_pai,
            'parent_id': self.parent_id,  # Parent product ID for variations
            'has_variants': len(self.variants) > 0 if self.variants else False,  # Flag indicating if product has variants
            'allow_stock_movement': (self.parent_id is not None) or (not (len(self.variants) > 0 if self.variants else False)),

            # Informações do setor responsável
            'setor_responsavel_id': self.setor_responsavel_id,
            'setor_responsavel_nome': self.setor_responsavel.nome if self.setor_responsavel else None,

            # Campos JSON mantidos para compatibilidade/legado
            'atributos': self.atributos,  # attributes → atributos
            'precificacao': self.precificacao,  # pricing → precificacao (LEGACY)
            'dados_estoque': self.dados_estoque,  # inventory_data → dados_estoque (LEGACY)

            'artworks': [artwork.to_dict(use_updated_url=True) for artwork in self.artworks] if self.artworks else [],

            # Novos campos para suporte a variações, composições e kits
            'formato': self.formato,
            'herdar_dados_pai': self.herdar_dados_pai,
            'herdar_bom_pai': self.herdar_bom_pai,

            # Planejamento de Produção
            'estoque_seguranca_dias': self.estoque_seguranca_dias,
            'ponto_ressuprimento': self.ponto_ressuprimento,
            'lote_economico': self.lote_economico,
            'curva_abc': self.curva_abc,

            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

        # Include variants if requested and if they exist
        if include_variants and self.variants:
            result['variants'] = [variant.to_dict(include_variants=False) for variant in self.variants]

        return result

# --- Relationships definitions at the bottom ---
Product.categoria = db.relationship('Categoria', backref='produtos_cat')
Product.unidade_medida = db.relationship('UnidadeMedida', backref='produtos_uom')
Product.artworks = db.relationship('ProductArtwork', back_populates='product', cascade='all, delete-orphan')
Product.variants = db.relationship('Product', backref=db.backref('parent', remote_side=[Product.id]))
Product.setor_responsavel = db.relationship('Setor', backref='produtos_responsaveis')

