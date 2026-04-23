"""
Módulo de gestão de demandas de produção.

Sub-módulos:
- core: CRUD de demandas, normalização, enrich de dados
- items: Gestão de itens da demanda
- collections: Coletas e entrega_producao
- status: Transições de status
"""

from .core import DemandaCoreService
from .items import DemandaItemsService
from .collections import DemandaCollectionsService
from .status import DemandaStatusService

__all__ = [
    'DemandaCoreService',
    'DemandaItemsService',
    'DemandaCollectionsService',
    'DemandaStatusService',
]
