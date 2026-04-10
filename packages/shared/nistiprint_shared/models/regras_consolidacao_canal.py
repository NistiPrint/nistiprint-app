"""
Regras Consolidacao Canal - Model.

Modelo para configuração de critérios de consolidação de pedidos em demandas
de produção por canal e modalidade.

Exemplo de uso:
    - Canal: "Shopee Principal"
    - Modalidade: EXPRESS
    - Janela de agrupamento: 2 horas
    - Agrupar por produto/miolo/data: true
    - Comportamento pós-edição: ADICIONAR_COM_SINALIZACAO
"""

from typing import Optional, Dict, Any, List
from datetime import datetime


class RegrasConsolidacaoCanal:
    """
    Representa regras de consolidação de pedidos por canal e modalidade.
    
    Attributes:
        id: ID da regra
        canal_venda_id: ID do canal de venda (NULL = regra global)
        modalidade: Modalidade logística (NULL = todas)
        agrupar_por_produto: Se agrupa por produto
        agrupar_por_miolo: Se agrupa por miolo
        agrupar_por_data_entrega: Se agrupa por data de entrega
        janela_agrupamento_horas: Janela de tempo para agrupamento (deslizante)
        comportamento_pos_edicao: ADICIONAR_COM_SINALIZACAO ou CRIAR_NOVO_RASCUNHO
        comportamento_pos_publicacao: CRIAR_NOVO_RASCUNHO ou SUGERIR_FUSAO
        ativo: Se a regra está ativa
        created_at: Data de criação
        updated_at: Data de atualização
    """
    
    MODALIDADES_VALIDAS = ['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA']
    COMPORTAMENTOS_VALIDOS = ['ADICIONAR_COM_SINALIZACAO', 'CRIAR_NOVO_RASCUNHO']
    COMPORTAMENTOS_PUBLICACAO = ['CRIAR_NOVO_RASCUNHO', 'SUGERIR_FUSAO']
    
    def __init__(
        self,
        id: Optional[int] = None,
        canal_venda_id: Optional[int] = None,
        modalidade: Optional[str] = None,
        agrupar_por_produto: bool = True,
        agrupar_por_miolo: bool = True,
        agrupar_por_data_entrega: bool = True,
        janela_agrupamento_horas: int = 4,
        comportamento_pos_edicao: str = 'ADICIONAR_COM_SINALIZACAO',
        comportamento_pos_publicacao: str = 'CRIAR_NOVO_RASCUNHO',
        ativo: bool = True,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.canal_venda_id = canal_venda_id
        self.modalidade = modalidade
        self.agrupar_por_produto = agrupar_por_produto
        self.agrupar_por_miolo = agrupar_por_miolo
        self.agrupar_por_data_entrega = agrupar_por_data_entrega
        self.janela_agrupamento_horas = janela_agrupamento_horas
        self.comportamento_pos_edicao = comportamento_pos_edicao
        self.comportamento_pos_publicacao = comportamento_pos_publicacao
        self.ativo = ativo
        self.created_at = created_at
        self.updated_at = updated_at
    
    def validate(self) -> List[str]:
        """
        Valida a regra de consolidação.
        
        Returns:
            Lista de mensagens de erro (vazia se válido)
        """
        errors = []
        
        if self.modalidade and self.modalidade not in self.MODALIDADES_VALIDAS:
            errors.append(f"modalidade deve ser uma de: {', '.join(self.MODALIDADES_VALIDAS)} ou NULL")
        
        if self.comportamento_pos_edicao not in self.COMPORTAMENTOS_VALIDOS:
            errors.append(f"comportamento_pos_edicao deve ser uma de: {', '.join(self.COMPORTAMENTOS_VALIDOS)}")
        
        if self.comportamento_pos_publicacao not in self.COMPORTAMENTOS_PUBLICACAO:
            errors.append(f"comportamento_pos_publicacao deve ser uma de: {', '.join(self.COMPORTAMENTOS_PUBLICACAO)}")
        
        if self.janela_agrupamento_horas < 0 or self.janela_agrupamento_horas > 168:  # 0 a 1 semana
            errors.append("janela_agrupamento_horas deve estar entre 0 e 168")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            'id': self.id,
            'canal_venda_id': self.canal_venda_id,
            'modalidade': self.modalidade,
            'agrupar_por_produto': self.agrupar_por_produto,
            'agrupar_por_miolo': self.agrupar_por_miolo,
            'agrupar_por_data_entrega': self.agrupar_por_data_entrega,
            'janela_agrupamento_horas': self.janela_agrupamento_horas,
            'comportamento_pos_edicao': self.comportamento_pos_edicao,
            'comportamento_pos_publicacao': self.comportamento_pos_publicacao,
            'ativo': self.ativo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RegrasConsolidacaoCanal':
        """Cria instância a partir de dicionário."""
        return cls(
            id=data.get('id'),
            canal_venda_id=data.get('canal_venda_id'),
            modalidade=data.get('modalidade'),
            agrupar_por_produto=data.get('agrupar_por_produto', True),
            agrupar_por_miolo=data.get('agrupar_por_miolo', True),
            agrupar_por_data_entrega=data.get('agrupar_por_data_entrega', True),
            janela_agrupamento_horas=data.get('janela_agrupamento_horas', 4),
            comportamento_pos_edicao=data.get('comportamento_pos_edicao', 'ADICIONAR_COM_SINALIZACAO'),
            comportamento_pos_publicacao=data.get('comportamento_pos_publicacao', 'CRIAR_NOVO_RASCUNHO'),
            ativo=data.get('ativo', True),
            created_at=cls._parse_datetime(data.get('created_at')),
            updated_at=cls._parse_datetime(data.get('updated_at'))
        )
    
    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse datetime de string ISO ou timestamp."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def eh_regra_global(self) -> bool:
        """Verifica se é regra global (canal_venda_id NULL)."""
        return self.canal_venda_id is None
    
    def eh_regra_geral_modalidade(self) -> bool:
        """Verifica se é regra geral para todas as modalidades (modalidade NULL)."""
        return self.modalidade is None
    
    def cria_demanda_direta(self) -> bool:
        """
        Verifica se deve criar demanda direta sem rascunho.
        
        Returns:
            True se janela_agrupamento_horas = 0
        """
        return self.janela_agrupamento_horas == 0
    
    def deve_agrupar(self, outro_pedido: Dict[str, Any], referencia: Dict[str, Any]) -> bool:
        """
        Verifica se dois pedidos devem ser agrupados com base nas regras.
        
        Args:
            outro_pedido: Dados do outro pedido
            referencia: Dados do pedido de referência
        
        Returns:
            True se devem ser agrupados
        """
        from datetime import datetime, timedelta
        
        # Verificar janela de tempo
        try:
            data_outro = self._parse_date(outro_pedido.get('created_at'))
            data_referencia = self._parse_date(referencia.get('created_at'))
            
            if data_outro and data_referencia:
                diferenca_horas = abs((data_outro - data_referencia).total_seconds() / 3600)
                
                if diferenca_horas > self.janela_agrupamento_horas:
                    return False
        except Exception:
            return False
        
        # Verificar produto
        if self.agrupar_por_produto:
            if outro_pedido.get('produto_id') != referencia.get('produto_id'):
                return False
        
        # Verificar miolo
        if self.agrupar_por_miolo:
            if outro_pedido.get('id_produto_miolo') != referencia.get('id_produto_miolo'):
                return False
        
        # Verificar data de entrega
        if self.agrupar_por_data_entrega:
            if outro_pedido.get('data_entrega') != referencia.get('data_entrega'):
                return False
        
        return True
    
    def _parse_date(self, value: Any) -> Optional[datetime]:
        """Parse date de string ISO."""
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    
    def __repr__(self) -> str:
        canal_str = f"canal={self.canal_venda_id}" if self.canal_venda_id else "GLOBAL"
        modal_str = f"modalidade={self.modalidade}" if self.modalidade else "TODAS"
        return f"RegrasConsolidacaoCanal(id={self.id}, {canal_str}, {modal_str}, janela={self.janela_agrupamento_horas}h)"
