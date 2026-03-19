"""
Módulo de alocação de estoque para demandas.

Sub-módulos:
- estoque: Alocação/reserva de estoque
- queue: Fila de processamento (agendar/processar)
- waterfall: Lógica recursiva BOM/insumos
"""

from .estoque import DemandaAlocacaoEstoqueService, demanda_alocacao_estoque_service
from .queue import DemandaAlocacaoQueueService, demanda_alocacao_queue_service
from .waterfall import DemandaAlocacaoWaterfallService, demanda_alocacao_waterfall_service

__all__ = [
    'DemandaAlocacaoEstoqueService',
    'DemandaAlocacaoQueueService',
    'DemandaAlocacaoWaterfallService',
    'demanda_alocacao_estoque_service',
    'demanda_alocacao_queue_service',
    'demanda_alocacao_waterfall_service',
]
