"""
Módulo de relatórios e dashboards de demandas.

Sub-módulos:
- dashboard: Sumários, KPIs
- kanban: Painel por setores
- production: Logs diários, consolidação
"""

from .dashboard import DemandaReportingDashboardService
from .kanban import DemandaReportingKanbanService
from .production import DemandaReportingProductionService

__all__ = [
    'DemandaReportingDashboardService',
    'DemandaReportingKanbanService',
    'DemandaReportingProductionService',
]
