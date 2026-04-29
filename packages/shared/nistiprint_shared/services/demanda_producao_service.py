"""
Demanda Producao Service - Facade para gestão de demandas de produção.

Este arquivo atua como uma Facade que delega chamadas para os módulos especializados:
- demanda.core: CRUD de demandas, enrich, normalização
- demanda.items: Gestão de itens da demanda
- demanda.collections: Coletas e entrega_producao
- demanda.status: Transições de status
- demanda_alocacao.estoque: Alocação/reserva de estoque
- demanda_alocacao.queue: Fila de processamento
- demanda_alocacao.waterfall: Lógica recursiva BOM/insumos
- demanda_reporting.dashboard: Sumários, KPIs
- demanda_reporting.kanban: Painel por setores
- demanda_reporting.production: Logs diários, consolidação

Compatibilidade: Este arquivo mantém 100% de compatibilidade com código existente.
"""

from datetime import datetime, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.auditoria_service import auditoria_service
from nistiprint_shared.services.estoque_service import estoque_service
from nistiprint_shared.services.system_log_service import system_log_service
from nistiprint_shared.services.product_service import product_service
from nistiprint_shared.services.bom_service import bom_service
from nistiprint_shared.services.order_tracker_service import order_tracker_service
from nistiprint_shared.services.daily_production_log_service import daily_production_log_service
from nistiprint_shared.services.app_config_service import app_config_service
from nistiprint_shared.services.system_events_log_service import system_events_log_service
from nistiprint_shared.services.previsao_consumo_service import previsao_consumo_service
from nistiprint_shared.services.unit_of_work import UnitOfWork
from typing import List, Dict, Any, Optional
import uuid
import logging
from nistiprint_shared.utils.date_utils import get_now, get_now_iso

# Importar serviços especializados
from .demanda.core import DemandaCoreService, demanda_core_service
from .demanda.items import DemandaItemsService, demanda_items_service
from .demanda.collections import DemandaCollectionsService, demanda_collections_service
from .demanda.status import DemandaStatusService, demanda_status_service
from .demanda_alocacao.estoque import DemandaAlocacaoEstoqueService, demanda_alocacao_estoque_service
from .demanda_alocacao.queue import DemandaAlocacaoQueueService, demanda_alocacao_queue_service
from .demanda_alocacao.waterfall import DemandaAlocacaoWaterfallService, demanda_alocacao_waterfall_service
from .demanda_reporting.dashboard import DemandaReportingDashboardService, demanda_reporting_dashboard_service
from .demanda_reporting.kanban import DemandaReportingKanbanService, demanda_reporting_kanban_service
from .demanda_reporting.production import DemandaReportingProductionService, demanda_reporting_production_service

logger = logging.getLogger(__name__)

class DemandaProducaoService:
    """
    Facade unificada para todos os serviços relacionados a demandas de produção.
    """

    def __init__(self):
        # Delegados especializados
        self._core = demanda_core_service
        self._items = demanda_items_service
        self._collections = demanda_collections_service
        self._status = demanda_status_service
        self._alocacao_estoque = demanda_alocacao_estoque_service
        self._alocacao_queue = demanda_alocacao_queue_service
        self._alocacao_waterfall = demanda_alocacao_waterfall_service
        self._report_dashboard = demanda_reporting_dashboard_service
        self._report_kanban = demanda_reporting_kanban_service
        self._report_production = demanda_reporting_production_service

    # ========================================================================
    # MÉTODOS CORE (demanda.core)
    # ========================================================================

    def get_all_demandas(self) -> List[Dict[str, Any]]:
        """Busca todas as demandas."""
        return self._core.get_all_demandas()

    def get_demandas_by_ids(self, demanda_ids: List[str]) -> List[Dict[str, Any]]:
        """Busca múltiplas demandas em lote."""
        return self._core.get_demandas_by_ids(demanda_ids)

    def get_items_for_multiple_demandas(self, demanda_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Busca itens de múltiplas demandas em uma única chamada."""
        return self._core.get_items_for_multiple_demandas(demanda_ids)

    def get_demanda_with_itens(self, demanda_id: str) -> Dict[str, Any]:
        """Busca demanda com seus itens."""
        return self._core.get_demanda_with_itens(demanda_id)

    def _resolve_miolo_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve e associa o ID do produto miolo para um item da demanda."""
        return self._core._resolve_miolo_for_item(item)

    def create_from_order(self, order_data: Dict[str, Any], user_id='System', **kwargs) -> Dict[str, Any]:
        """
        Cria demanda a partir de um pedido (Facade).
        Aceita is_flex, modalidade_logistica, canal_venda_id e marketplace_integration_id via kwargs.
        """
        return self._core.create_from_order(order_data, user_id, **kwargs)

    def criar_demanda_direta(self, nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
                             horario_coleta_especifico=None, data_finalizacao_prevista=None,
                             observacoes=None, user_id='System', tipo_demanda='PLATAFORMA',
                             status='EM_PRODUCAO', pedido_id=None, **kwargs) -> Dict[str, Any]:
        """Cria demanda direta."""
        return self._core.criar_demanda_direta(
            nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
            horario_coleta_especifico, data_finalizacao_prevista,
            observacoes, user_id, tipo_demanda, status, pedido_id, **kwargs
        )

    def criar_demanda_empresas(self, nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
                             horario_coleta_especifico=None, data_finalizacao_prevista=None,
                             observacoes=None, user_id='System', tipo_demanda='B2B',
                             status='Em Produção', **kwargs) -> Dict[str, Any]:
        """Cria demanda para empresas (B2B)."""
        return self._core.criar_demanda_empresas(
            nome_demanda, canal_venda_id, data_entrega_str, lista_de_itens,
            horario_coleta_especifico, data_finalizacao_prevista,
            observacoes, user_id, tipo_demanda, status, **kwargs
        )

    def update_demanda_details(self, demanda_id: str, updates: Dict[str, Any], user_id: str = 'System') -> Dict[str, Any]:
        """Atualiza detalhes da demanda."""
        return self._core.update_demanda_details(demanda_id, updates, user_id)

    def atualizar_demanda_completa(self, demanda_id: str, updates: Dict[str, Any], itens: List[Dict[str, Any]], user_id: str = 'System') -> Dict[str, Any]:
        """Atualiza demanda e seus itens em transação atômica."""
        return self._core.atualizar_demanda_completa(demanda_id, updates, itens, user_id)

    def deletar_demanda(self, demanda_id: str, user_id='System') -> bool:
        """Deleta uma demanda e seus itens."""
        return self._core.deletar_demanda(demanda_id, user_id)

    # ========================================================================
    # MÉTODOS ITEMS (demanda.items)
    # ========================================================================

    def registrar_producao_incremental(self, demanda_id, item_id, producao_incremental, user_id='System',
                                      origem_tipo=1, retroactive_date=None, correlation_id=None):
        """Registra produção incremental (capas impressas, produzidas, miolos)."""
        return self._items.registrar_producao_incremental(
            demanda_id, item_id, producao_incremental, user_id,
            origem_tipo, retroactive_date, correlation_id
        )

    def registrar_producao_lote(self, demanda_id: str, updates: List[Dict[str, Any]], user_id: str = 'System',
                                origem_tipo: int = 1, retroactive_date: str = None, 
                                correlation_id: str = None) -> Dict[str, Any]:
        """Registra produção para múltiplos itens em lote."""
        return self._items.registrar_producao_lote(
            demanda_id, updates, user_id, origem_tipo, retroactive_date, correlation_id
        )

    def finalizar_item(self, demanda_id, item_id, user_id='System'):
        """Finaliza um item da demanda."""
        return self._items.finalizar_item(demanda_id, item_id, user_id)

    def finalizar_item_parcial(self, demanda_id, item_id, quantidade, user_id='System'):
        """Finaliza parcialmente um item da demanda."""
        return self._items.finalizar_item_parcial(demanda_id, item_id, quantidade, user_id)

    def estornar_finalizacao_item(self, demanda_id, item_id, quantidade, user_id='System'):
        """Estorna finalização de um item."""
        return self._items.estornar_finalizacao_item(demanda_id, item_id, quantidade, user_id)

    # ========================================================================
    # MÉTODOS STATUS (demanda.status)
    # ========================================================================

    def transicionar_status(self, demanda_id: str, novo_status: str, user_id: str = 'System') -> Dict[str, Any]:
        """Altera o status de uma demanda."""
        return self._status.transicionar_status(demanda_id, novo_status, user_id)

    def auto_atualizar_status_demanda(self, demanda_id: str) -> str:
        """Avalia e atualiza automaticamente o status da demanda com base nos itens."""
        return self._status.auto_atualizar_status_demanda(demanda_id)

    # ========================================================================
    # MÉTODOS COLLECTIONS (demanda.collections)
    # ========================================================================

    def registrar_coleta(self, demanda_id: str, quantidade: int, ponto_coleta_id: Optional[int] = None, 
                         observacoes: Optional[str] = None, user_id: str = 'System') -> Dict[str, Any]:
        """Registra a coleta (física/saída) de uma quantidade da demanda."""
        return self._collections.registrar_coleta(demanda_id, quantidade, ponto_coleta_id, observacoes, user_id)

    def registrar_saida_item_producao(self, item_id: int, quantidade: int, user_id: str = 'System') -> Dict[str, Any]:
        """Registra a saída física de unidades produzidas de um item."""
        return self._collections.registrar_saida_item_producao(item_id, quantidade, user_id)

    # ========================================================================
    # MÉTODOS ALOCAÇÃO ESTOQUE (demanda_alocacao.*)
    # ========================================================================

    def processar_reserva_inteligente(self, demanda_id, itens_payload, user_id):
        """Calcula e executa reserva de estoque (V2)."""
        return self._alocacao_estoque.processar_reserva_inteligente_v2(demanda_id, itens_payload, user_id)

    def processar_fila_estoque(self, limit=10):
        """Processa a fila de tarefas de estoque."""
        return self._alocacao_queue.processar_proxima_tarefa(limit)

    # ========================================================================
    # MÉTODOS REPORTING (demanda_reporting.*)
    # ========================================================================

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Obtém resumo consolidado de produção para a lista de demandas."""
        return self._report_production.get_daily_production_summary()

    def get_kanban_data(self, setor_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Obtém dados para o quadro Kanban."""
        return self._report_kanban.get_kanban_board(setor_id)

    def get_painel_producao_setores(self, setor_id_ou_nome: Optional[int] = None) -> Dict[str, Any]:
        """Obtém dados do painel de produção organizado por setores/colunas Kanban."""
        return self._report_kanban.get_painel_producao_setores(setor_id_ou_nome)

    def get_daily_production_summary(self) -> Dict[str, Any]:
        """Obtém resumo diário de produção consolidado."""
        return self._report_production.get_daily_production_summary()

    def get_demandas_consolidadas(self, data_inicio: str, data_fim: str) -> List[Dict[str, Any]]:
        """Obtém demandas consolidadas para relatório."""
        return self._report_production.get_consolidated_report(data_inicio, data_fim)


# Instância única singleton
demanda_producao_service = DemandaProducaoService()
