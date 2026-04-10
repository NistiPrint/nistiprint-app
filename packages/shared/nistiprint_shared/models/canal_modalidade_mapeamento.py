"""
Canal Modalidade Mapeamento - Model.

Modelo para mapeamento configurável de padrões de servico_logistico
para modalidade logística interna (STANDARD, EXPRESS, FULFILLMENT, RETIRADA).

Exemplo de uso:
    - Canal: "Shopee Principal"
    - Padrões: ['%flex%', '%rápida%', 'Entrega Rápida']
    - Modalidade: EXPRESS
    - Prioridade: 100
"""

from typing import List, Optional, Dict, Any
from datetime import datetime


class CanalModalidadeMapeamento:
    """
    Representa um mapeamento de padrão de serviço logístico para modalidade.
    
    Attributes:
        id: ID do mapeamento
        canal_venda_id: ID do canal de venda
        padrao_servico: Padrão LIKE para matching (ex: '%flex%')
        modalidade: Modalidade logística (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)
        prioridade: Prioridade do padrão (maior = mais específico)
        ativo: Se o mapeamento está ativo
        created_at: Data de criação
        updated_at: Data de atualização
    """
    
    MODALIDADES_VALIDAS = ['STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA']
    
    def __init__(
        self,
        id: Optional[int] = None,
        canal_venda_id: Optional[int] = None,
        padrao_servico: Optional[str] = None,
        modalidade: Optional[str] = None,
        prioridade: int = 0,
        ativo: bool = True,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.canal_venda_id = canal_venda_id
        self.padrao_servico = padrao_servico
        self.modalidade = modalidade
        self.prioridade = prioridade
        self.ativo = ativo
        self.created_at = created_at
        self.updated_at = updated_at
    
    def validate(self) -> List[str]:
        """
        Valida o mapeamento.
        
        Returns:
            Lista de mensagens de erro (vazia se válido)
        """
        errors = []
        
        if not self.canal_venda_id:
            errors.append("canal_venda_id é obrigatório")
        
        if not self.padrao_servico:
            errors.append("padrao_servico é obrigatório")
        
        if not self.modalidade:
            errors.append("modalidade é obrigatória")
        elif self.modalidade not in self.MODALIDADES_VALIDAS:
            errors.append(f"modalidade deve ser uma de: {', '.join(self.MODALIDADES_VALIDAS)}")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            'id': self.id,
            'canal_venda_id': self.canal_venda_id,
            'padrao_servico': self.padrao_servico,
            'modalidade': self.modalidade,
            'prioridade': self.prioridade,
            'ativo': self.ativo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CanalModalidadeMapeamento':
        """Cria instância a partir de dicionário."""
        return cls(
            id=data.get('id'),
            canal_venda_id=data.get('canal_venda_id'),
            padrao_servico=data.get('padrao_servico'),
            modalidade=data.get('modalidade'),
            prioridade=data.get('prioridade', 0),
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
            # Tenta parse ISO format
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def matches_servico(self, servico_logistico: str) -> bool:
        """
        Verifica se um servico_logístico casa com o padrão.
        
        Args:
            servico_logistico: String do serviço logístico (ex: "Entrega Rápida Shopee")
        
        Returns:
            True se casar com o padrão (ILIKE)
        """
        if not servico_logistico or not self.padrao_servico:
            return False
        
        # Converte padrão LIKE para regex simples
        # % = .* (qualquer coisa)
        # _ = . (um caractere)
        padrao_regex = self.padrao_servico.upper().replace('%', '.*').replace('_', '.')
        
        import re
        return bool(re.search(padrao_regex, servico_logistico.upper()))
    
    def __repr__(self) -> str:
        return f"CanalModalidadeMapeamento(id={self.id}, canal={self.canal_venda_id}, modalidade={self.modalidade}, padrao={self.padrao_servico})"
