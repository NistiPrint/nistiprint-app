from typing import List, Dict, Any, Optional
from .estoque import demanda_alocacao_estoque_service, StockProcessingResult

class DemandaAlocacaoQueueService:
    """
    Wrapper de compatibilidade para a fila de processamento de estoque.
    Delega a execução real para o DemandaAlocacaoEstoqueService em estoque.py.
    """
    def __init__(self):
        self._service = demanda_alocacao_estoque_service

    def agendar_processamento_estoque(self, *args, **kwargs):
        return self._service.agendar_processamento_estoque(*args, **kwargs)

    def agendar_reserva_inteligente(self, *args, **kwargs):
        return self._service.agendar_reserva_inteligente(*args, **kwargs)

    def processar_fila_estoque(self, limit=10):
        return self._service.processar_fila_estoque(limit=limit)

    # Métodos internos delegados se necessário por outros módulos
    def _registrar_alocacao_estoque(self, *args, **kwargs):
        return self._service._registrar_alocacao_estoque(*args, **kwargs)

    def _marcar_alocacao_cancelada(self, *args, **kwargs):
        return self._service._marcar_alocacao_cancelada(*args, **kwargs)

    def _calcular_saldo_a_processar(self, *args, **kwargs):
        return self._service._calcular_saldo_a_processar(*args, **kwargs)

    def get_item_by_id(self, *args, **kwargs):
        return self._service.get_item_by_id(*args, **kwargs)

demanda_alocacao_queue_service = DemandaAlocacaoQueueService()
