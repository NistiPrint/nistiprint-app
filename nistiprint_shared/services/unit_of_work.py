from typing import Optional, Callable, Any
from nistiprint_shared.services.auditoria_service import auditoria_service

class UnitOfWork:
    """
    Implementa o padrão Unit of Work.
    
    NOTA: Adaptado para Supabase REST Client.
    Como o cliente REST não suporta transações interativas do lado do cliente,
    esta classe atua como um wrapper "pass-through" para manter a compatibilidade
    da API e permitir logging de auditoria centralizado.
    
    ATENÇÃO: Operações executadas aqui NÃO são atômicas em conjunto.
    Se a atomicidade for crítica, considere mover a lógica para uma RPC (Stored Procedure).
    """

    def __init__(self, user_id: Optional[str] = None):
        self.user_id = user_id
        self._active = False
        self._committed = False
        self._rolled_back = False

    def begin(self):
        """Inicia o contexto de trabalho."""
        if self._active:
            raise RuntimeError("UnitOfWork já está ativo")
        
        self._active = True
        self._committed = False
        self._rolled_back = False

    def commit(self):
        """Finaliza o contexto de trabalho."""
        if not self._active:
            raise RuntimeError("Nenhum UnitOfWork ativo para confirmar")
        
        self._committed = True
        self._active = False

    def rollback(self):
        """Finaliza o contexto de trabalho (sem rollback real no DB)."""
        if not self._active:
            raise RuntimeError("Nenhum UnitOfWork ativo para reverter")

        self._rolled_back = True
        self._active = False

    def execute_in_transaction(self, operation: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Executa uma operação imediatamente.
        A transação não é injetada pois não é suportada pelo cliente REST.

        Args:
            operation: Função a ser executada
            *args: Argumentos posicionais
            **kwargs: Argumentos nomeados

        Returns:
            Resultado da operação
        """
        if not self._active:
            raise RuntimeError("UnitOfWork não está ativo")

        # Remove 'transaction' se foi passado explicitamente para evitar erros
        if 'transaction' in kwargs:
            del kwargs['transaction']

        return operation(*args, **kwargs)

    def log_audit_event(self, event_type: str, payload: dict):
        """
        Registra um evento de auditoria.

        Args:
            event_type: Tipo do evento
            payload: Dados do evento
        """
        if not self._active:
            raise RuntimeError("UnitOfWork não está ativo para registrar evento de auditoria")

        auditoria_service.log_event(
            event_type=event_type,
            payload=payload,
            user_id=self.user_id
        )

    @property
    def is_active(self) -> bool:
        """Verifica se está ativo."""
        return self._active

    @property
    def is_committed(self) -> bool:
        """Verifica se foi confirmado."""
        return self._committed

    @property
    def is_rolled_back(self) -> bool:
        """Verifica se foi revertido."""
        return self._rolled_back

    def __enter__(self):
        """Suporte para uso com 'with' statement."""
        self.begin()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Suporte para uso com 'with' statement."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
            return False  # Re-raise a exceção

