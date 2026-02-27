from ..database.database import db
from datetime import datetime
from sqlalchemy import CheckConstraint
from models import entrega_producao

class DemandaProducao(db.Model):
    __tablename__ = 'demandas_producao'

    id = db.Column(db.Integer, primary_key=True)
    demanda_id = db.Column(db.String(255), nullable=False, unique=True)  # Original Firestore document ID
    descricao = db.Column(db.Text)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)
    quantidade = db.Column(db.Integer)
    data_entrega = db.Column(db.Date)
    prioridade = db.Column(db.Integer, default=0)
    STATUS_OPTIONS = ['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'CONCLUIDO', 'CANCELADO']
    status = db.Column(db.String(50), default='AGUARDANDO')
    responsavel_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    
    # Novos campos estruturados
    canal_venda_id = db.Column(db.Integer, db.ForeignKey('canais_venda.id'), nullable=True)
    horario_coleta = db.Column(db.Time)
    tipo_demanda = db.Column(db.String(50), default='PLATAFORMA')  # Valores padronizados: PLATAFORMA, B2B, FULFILLMENT, ESTOQUE_INTERNO
    observacoes = db.Column(db.Text)
    prioridade_manual = db.Column(db.Integer, default=0)
    pedido_numero = db.Column(db.String(100))
    data_conclusao = db.Column(db.DateTime)
    is_flex = db.Column(db.Boolean, default=False)
    fulfillment = db.Column(db.Boolean, default=False)

    # Campos adicionados na refatoração da arquitetura
    modalidade_logistica = db.Column(db.String(20), default='STANDARD')  # STANDARD, EXPRESS, FULFILLMENT, RETIRADA
    classificacao_cliente = db.Column(db.String(10), default='B2C')  # B2C, B2B, INTERNO

    # Planejamento Avançado
    categoria_demanda = db.Column(db.Text)
    prioridade_tipo = db.Column(db.Text)
    data_limite_execucao = db.Column(db.Date)
    data_inicio_planejada = db.Column(db.DateTime)
    data_fim_planejada = db.Column(db.DateTime)
    setores_envolvidos = db.Column(db.JSON)
    categoria_temporal = db.Column(db.Text)
    data_promessa_cliente = db.Column(db.Date)
    data_maxima_entrega = db.Column(db.Date)

    # Campo para capacidade requerida por setor/turno
    capacidade_requerida = db.Column(db.JSON)  # Capacidade requerida para a produção da demanda, segmentada por setor/turno

    dados_adicionais = db.Column(db.JSON)  # Mantido para compatibilidade/extensibilidade
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            tipo_demanda.in_(['PLATAFORMA', 'B2B', 'FULFILLMENT', 'ESTOQUE_INTERNO']),
            name='check_tipo_demanda_values'
        ),
        CheckConstraint(
            status.in_(STATUS_OPTIONS),
            name='check_demanda_status_values'
        )
    )

    def to_dict(self):
        def format_datetime(dt):
            if dt is None: return None
            if isinstance(dt, str): return dt
            return dt.isoformat()

        # Tenta identificar o miolo a partir dos itens para o cabeçalho
        first_item = self.itens[0] if self.itens else None
        id_produto_miolo = first_item.id_produto_miolo if first_item else None
        produto_miolo_nome = first_item.produto_miolo.nome if first_item and first_item.produto_miolo else (first_item.miolo_nome if first_item else None)

        # Identifica o deadline final baseado nas regras logísticas do canal
        deadline_final = self.horario_coleta.isoformat() if self.horario_coleta else "23:59"
        
        # Tenta buscar via tabela estruturada primeiro
        if self.canal_venda and self.canal_venda.regras_log:
            regras = [r for r in self.canal_venda.regras_log if r.modalidade == self.modalidade_logistica]
            if regras:
                try:
                    horarios = [r.horario_limite.isoformat() for r in regras if r.horario_limite]
                    if horarios:
                        deadline_final = max(horarios)
                except:
                    pass

        return {
            'id': self.id,
            'demanda_id': self.demanda_id,
            'descricao': self.descricao,
            'nome': self.descricao, # Alias usado no frontend
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,
            'id_produto_miolo': id_produto_miolo,
            'produto_miolo_nome': produto_miolo_nome,
            'quantidade': self.quantidade,
            'data_entrega': format_datetime(self.data_entrega),
            'prioridade': self.prioridade,
            'status': self.status,
            'responsavel_id': self.responsavel_id,
            'responsavel_nome': self.responsavel.nome if self.responsavel else None,
            'canal_venda_id': self.canal_venda_id,
            'canal_venda_nome': self.canal_venda.nome if self.canal_venda else None,
            'horario_coleta': self.horario_coleta.isoformat() if self.horario_coleta else None,
            'deadline_final': deadline_final,
            'tipo_demanda': self.tipo_demanda,
            'tipo_demanda_label': self.get_tipo_demanda_label(),  # Rótulo amigável para frontend
            'observacoes': self.observacoes,
            'prioridade_manual': self.prioridade_manual,
            'pedido_numero': self.pedido_numero,
            'data_conclusao': format_datetime(self.data_conclusao),
            'is_flex': self.is_flex,
            'fulfillment': self.fulfillment,
            'modalidade_logistica': self.modalidade_logistica,
            'classificacao_cliente': self.classificacao_cliente,
            'categoria_demanda': self.categoria_demanda,
            'prioridade_tipo': self.prioridade_tipo,
            'data_limite_execucao': format_datetime(self.data_limite_execucao),
            'data_inicio_planejada': format_datetime(self.data_inicio_planejada),
            'data_fim_planejada': format_datetime(self.data_fim_planejada),
            'setores_envolvidos': self.setores_envolvidos,
            'categoria_temporal': self.categoria_temporal,
            'data_promessa_cliente': format_datetime(self.data_promessa_cliente),
            'data_maxima_entrega': format_datetime(self.data_maxima_entrega),
            'dados_adicionais': self.dados_adicionais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

    def get_tipo_demanda_label(self):
        """Retorna o rótulo amigável para o tipo de demanda"""
        labels = {
            'PLATAFORMA': 'Venda Plataforma',
            'B2B': 'Venda Corporativa',
            'FULFILLMENT': 'Reposição Fulfillment',
            'ESTOQUE_INTERNO': 'Reposição Estoque Interno'
        }
        return labels.get(self.tipo_demanda, self.tipo_demanda)

    def get_modalidade_logistica_label(self):
        """Retorna o rótulo amigável para a modalidade logística"""
        labels = {
            'STANDARD': 'Envio Padrão',
            'EXPRESS': 'Entrega Expressa (Flex)',
            'FULFILLMENT': 'Fulfillment Externo',
            'RETIRADA': 'Retirada no Local'
        }
        return labels.get(self.modalidade_logistica, self.modalidade_logistica)

    def get_classificacao_cliente_label(self):
        """Retorna o rótulo amigável para a classificação do cliente"""
        labels = {
            'B2C': 'Cliente Final (B2C)',
            'B2B': 'Venda Corporativa (B2B)',
            'INTERNO': 'Uso Interno/Amostra'
        }
        return labels.get(self.classificacao_cliente, self.classificacao_cliente)

class DemandaProducaoItem(db.Model):
    __tablename__ = 'itens_demanda'

    id = db.Column(db.Integer, primary_key=True)
    demanda_id = db.Column(db.Integer, db.ForeignKey('demandas_producao.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)
    sku = db.Column(db.String(100))
    descricao = db.Column(db.String(500))
    quantidade = db.Column(db.Integer)

    # Controle de Produção
    capas_impressas_qtd = db.Column(db.Integer, default=0)
    capas_produzidas_qtd = db.Column(db.Integer, default=0)
    capas_prontas_retirada_qtd = db.Column(db.Integer, default=0)
    miolos_prontos_retirada_qtd = db.Column(db.Integer, default=0)
    expedicao_capas_retiradas_qtd = db.Column(db.Integer, default=0)
    expedicao_miolos_retirados_qtd = db.Column(db.Integer, default=0)
    status_item = db.Column(db.String(50), default='Pendente')
    miolo_nome = db.Column(db.String(255))
    id_produto_miolo = db.Column(db.Integer, db.ForeignKey('produtos.id'), nullable=True)
    variacao = db.Column(db.String(255))

    dados_adicionais = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        def format_datetime(dt):
            if dt is None: return None
            if isinstance(dt, str): return dt
            return dt.isoformat()

        return {
            'id': self.id,
            'demanda_id': self.demanda_id,
            'produto_id': self.produto_id,
            'produto_nome': self.produto.nome if self.produto else None,
            'sku': self.sku,
            'descricao': self.descricao,
            'item_descricao': self.descricao, # Alias para o frontend
            'quantidade': self.quantidade,
            'quantidade_total': self.quantidade, # Alias para o frontend
            'capas_impressas_qtd': self.capas_impressas_qtd,
            'capas_produzidas_qtd': self.capas_produzidas_qtd,
            'capas_prontas_retirada_qtd': self.capas_prontas_retirada_qtd,
            'miolos_prontos_retirada_qtd': self.miolos_prontos_retirada_qtd,
            'expedicao_capas_retiradas_qtd': self.expedicao_capas_retiradas_qtd,
            'expedicao_miolos_retirados_qtd': self.expedicao_miolos_retirados_qtd,
            'status_item': self.status_item,
            'miolo_nome': self.miolo_nome,
            'miolo_name': self.miolo_nome, # Alias para o frontend
            'id_produto_miolo': self.id_produto_miolo,
            'produto_miolo_nome': self.produto_miolo.nome if self.produto_miolo else None,
            'variacao': self.variacao,
            'dados_adicionais': self.dados_adicionais,
            'created_at': format_datetime(self.created_at),
            'updated_at': format_datetime(self.updated_at)
        }

# --- Relationships definitions at the bottom to avoid circular dependencies ---

# DemandaProducao Relationships
DemandaProducao.produto = db.relationship('Product', foreign_keys=[DemandaProducao.produto_id], backref='demandas_producao_como_produto')
DemandaProducao.responsavel = db.relationship('Usuario', backref='demandas_producao_como_responsavel')
DemandaProducao.itens = db.relationship('DemandaProducaoItem', 
                        back_populates='demanda_producao', 
                        cascade="all, delete-orphan",
                        primaryjoin="DemandaProducao.id == DemandaProducaoItem.demanda_id")
DemandaProducao.canal_venda = db.relationship('CanalVenda', backref='demandas_producao_vinculadas')

# DemandaProducaoItem Relationships
DemandaProducaoItem.demanda_producao = db.relationship('DemandaProducao', back_populates='itens')
DemandaProducaoItem.produto = db.relationship('Product', foreign_keys=[DemandaProducaoItem.produto_id], backref='itens_demanda_como_principal')
DemandaProducaoItem.produto_miolo = db.relationship('Product', foreign_keys=[DemandaProducaoItem.id_produto_miolo], backref='itens_demanda_como_miolo')
DemandaProducaoItem.entregas = db.relationship('EntregaProducao', back_populates='item_relacionado', cascade="all, delete-orphan")