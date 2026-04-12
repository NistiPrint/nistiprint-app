# ===========================================
# CORRELATION ID SERVICE
# ===========================================
# Serviço para gerenciar correlation_id para rastreamento end-to-end
# de operações assíncronas e síncronas
# ===========================================

import uuid
from contextvars import ContextVar
from typing import Optional

# Context variable para armazenar correlation_id no contexto de execução
_correlation_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


def generate_correlation_id() -> str:
    """
    Gera um novo correlation_id (UUID v4).
    
    Returns:
        str: correlation_id gerado
    """
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> None:
    """
    Define o correlation_id no contexto de execução atual.
    
    Args:
        correlation_id: correlation_id a ser definido
    """
    _correlation_context.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """
    Recupera o correlation_id do contexto de execução atual.
    
    Returns:
        Optional[str]: correlation_id se definido, None caso contrário
    """
    return _correlation_context.get()


def with_correlation(correlation_id: Optional[str] = None) -> str:
    """
    Define o correlation_id no contexto e retorna o valor.
    
    Se correlation_id não for fornecido, gera um novo.
    
    Args:
        correlation_id: correlation_id opcional
        
    Returns:
        str: correlation_id definido
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)
    return correlation_id


def clear_correlation_id() -> None:
    """
    Remove o correlation_id do contexto de execução.
    """
    _correlation_context.set(None)
