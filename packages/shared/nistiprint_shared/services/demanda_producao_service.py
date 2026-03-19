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

# Manter aliases para compatibilidade com imports legados
# Ex: from demanda_producao_service import demanda_core_service
demanda_core_service = demanda_core_service
demanda_items_service = demanda_items_service
demanda_collections_service = demanda_collections_service
demanda_status_service = demanda_status_service
demanda_alocacao_estoque_service = demanda_alocacao_estoque_service
demanda_alocacao_queue_service = demanda_alocacao_queue_service
demanda_alocacao_waterfall_service = demanda_alocacao_waterfall_service
demanda_reporting_dashboard_service = demanda_reporting_dashboard_service
demanda_reporting_kanban_service = demanda_reporting_kanban_service
demanda_reporting_production_service = demanda_reporting_production_service


class DemandaProducaoService:
    """
    Facade para gestão de demandas de produção.
    
    Este classe delega todas as chamadas para os serviços especializados,
    mantendo compatibilidade com o código existente.
    """
    
    def __init__(self):
        # Inicializar tabelas para compatibilidade
        self.demandas_table = supabase_db.table('demandas_producao')
        self.itens_table = supabase_db.table('itens_demanda')
        
        # Composição dos serviços especializados
        self._core = demanda_core_service
        self._items = demanda_items_service
        self._collections = demanda_collections_service
        self._status = demanda_status_service
        self._alocacao_estoque = demanda_alocacao_estoque_service
        self._alocacao_queue = demanda_alocacao_queue_service
        self._alocacao_waterfall = demanda_alocacao_waterfall_service
        self._reporting_dashboard = demanda_reporting_dashboard_service
        self._reporting_kanban = demanda_reporting_kanban_service
        self._reporting_production = demanda_reporting_production_service

    # ========================================================================
    # MÉTODOS CORE (demanda.core)
    # ========================================================================
    
    def _normalize_status(self, status: str) -> str:
        """Converte status legados para o novo padrão Upper Snake Case do banco de dados."""
        return self._core._normalize_status(status)

    def _process_demanda_dict(self, demanda: Dict[str, Any], itens: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend, incluindo agregações de itens."""
        return self._core._process_demanda_dict(demanda, itens)

    def _enrich_demanda_with_collection_totals(self, demanda_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Enriquece o dicionário da demanda com o somatório total de coletas."""
        return self._core._enrich_demanda_with_collection_totals(demanda_dict)

    def _enrich_items_with_stock(self, itens: List[Dict[str, Any]], deposito_id: Any = None) -> List[Dict[str, Any]]:
        """Adiciona informações de saldo de estoque (miolo e capas) aos itens em lote."""
        return self._core._enrich_items_with_stock(itens, deposito_id)

    def _process_item_dict(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Adiciona aliases e processa campos para o frontend."""
        return self._core._process_item_dict(item)

    def _get_aggregated_demandas(self, response_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Agrega dados de demandas com itens e coletas."""
        return self._core._get_aggregated_demandas(response_data)

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

    def create_from_order(self, order_data: Dict[str, Any], user_id='System') -> Dict[str, Any]:
        """Cria demanda a partir de um pedido."""
        return self._core.create_from_order(order_data, user_id)

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

    def _processar_reserva_inteligente_demanda(self, demanda_id, itens_payload, user_id):
        """Calcula e executa reserva de estoque seguindo lógica Waterfall."""
        return self._core._processar_reserva_inteligente_demanda(demanda_id, itens_payload, user_id)

    def _reservar_recursivo(self, produto_id, quantidade, deposito_id, report_list, nivel=0):
        """Motor recursivo de reserva."""
        return self._core._reservar_recursivo(produto_id, quantidade, deposito_id, report_list, nivel)

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
    
    def _atualizar_progresso_simples(self, item_id: str, campo: str, incremento: float):
        """Atualiza apenas o campo de progresso visual no item da demanda."""
        return self._items._atualizar_progresso_simples(item_id, campo, incremento)

    def _atualizar_progresso_simples_no_banco(self, item_id, campo, incremento):
        """Atualiza apenas o campo de progresso visual no item da demanda."""
        return self._items._atualizar_progresso_simples_no_banco(item_id, campo, incremento)

    def get_item_by_id(self, item_id):
        """Busca item por ID."""
        return self._items.get_item_by_id(item_id)

    def atualizar_progresso_item(self, demanda_id, item_id, quantities_to_update, user_id='System'):
        """Atualiza progresso de um item e dispara movimentações de estoque."""
        return self._items.atualizar_progresso_item(demanda_id, item_id, quantities_to_update, user_id)

    def _forcar_finalizacao_estoque_item(self, item_id, total_qty, user_id):
        """Força finalização de estoque de um item."""
        return self._items._forcar_finalizacao_estoque_item(item_id, total_qty, user_id)

    def finalizar_item(self, demanda_id, item_id, user_id='System'):
        """Finaliza um item da demanda."""
        return self._items.finalizar_item(demanda_id, item_id, user_id)

    def finalizar_item_parcial(self, demanda_id, item_id, quantidade_parcial, user_id='System'):
        """Finaliza parcialmente um item da demanda."""
        return self._items.finalizar_item_parcial(demanda_id, item_id, quantidade_parcial, user_id)

    def reverter_finalizacao_item(self, demanda_id, item_id, user_id='System'):
        """Reverte finalização de um item."""
        return self._items.reverter_finalizacao_item(demanda_id, item_id, user_id)

    def registrar_saida_item_distribuida(self, distributions, product_id, user_id='System', transaction=None):
        """Registra saída de item distribuída."""
        return self._items.registrar_saida_item_distribuida(distributions, product_id, user_id, transaction)

    # ========================================================================
    # MÉTODOS COLLECTIONS (demanda.collections)
    # ========================================================================
    
    def get_coletas_da_demanda(self, demanda_id: str) -> List[Dict[str, Any]]:
        """Busca o histórico de coletas para uma demanda específica."""
        return self._collections.get_coletas_da_demanda(demanda_id)

    def get_historico_coletas_global(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Busca o histórico global de coletas."""
        return self._collections.get_historico_coletas_global(limit)

    def marcar_como_coletado(self, demanda_id, user_id='System'):
        """Marca demanda como coletada."""
        return self._collections.marcar_como_coletado(demanda_id, user_id)

    def registrar_coleta_parcial(self, demanda_id: str, quantidade_coletar: int, user_id: str = 'System') -> Dict[str, Any]:
        """Registra coleta parcial de uma demanda."""
        return self._collections.registrar_coleta_parcial(demanda_id, quantidade_coletar, user_id)

    def _atualizar_status_demanda_apos_coleta(self, demanda_id: str, user_id: str = 'System') -> Dict[str, Any]:
        """Atualiza status da demanda após coleta."""
        return self._collections._atualizar_status_demanda_apos_coleta(demanda_id, user_id)

    def marcar_lote_como_coletado(self, demanda_ids, user_id='System'):
        """Marca lote de demandas como coletado."""
        return self._collections.marcar_lote_como_coletado(demanda_ids, user_id)

    # ========================================================================
    # MÉTODOS STATUS (demanda.status)
    # ========================================================================
    
    def _verificar_e_finalizar_demanda_automatica(self, demanda_id, user_id='System'):
        """Verifica e finaliza demanda automaticamente."""
        return self._status._verificar_e_finalizar_demanda_automatica(demanda_id, user_id)

    def finalizar_demanda_completa(self, demanda_id, user_id='System'):
        """Finaliza demanda completa."""
        return self._status.finalizar_demanda_completa(demanda_id, user_id)

    def _baixar_estoque_demanda(self, demanda_id: str, user_id: str = 'System'):
        """Efetiva saída de estoque para todos os itens de uma demanda."""
        return self._status._baixar_estoque_demanda(demanda_id, user_id)

    # ========================================================================
    # MÉTODOS ALOCAÇÃO ESTOQUE (demanda_alocacao.estoque)
    # ========================================================================
    
    def _registrar_alocacao_estoque(self, demanda_id: str, item_id: str, produto_id: str,
                                    correlation_id: str, quantidade: float, tipo_alocacao: str,
                                    processo_origem: str, metadata: dict = None):
        """Registra alocação de estoque na tabela demanda_alocacoes_estoque."""
        return self._alocacao_estoque._registrar_alocacao_estoque(
            demanda_id, item_id, produto_id, correlation_id, quantidade,
            tipo_alocacao, processo_origem, metadata
        )

    def _marcar_alocacao_processada(self, correlation_id: str):
        """Marca alocação como processada após consumo de estoque realizado."""
        return self._alocacao_estoque._marcar_alocacao_processada(correlation_id)

    def _marcar_alocacao_cancelada(self, correlation_id: str, motivo: str = None):
        """Cancela alocação (ex: em caso de estorno)."""
        return self._alocacao_estoque._marcar_alocacao_cancelada(correlation_id, motivo)

    def _buscar_alocacoes_por_item(self, item_id: str, produto_id: str = None) -> List[Dict[str, Any]]:
        """Busca todas as alocações ativas para um item."""
        return self._alocacao_estoque._buscar_alocacoes_por_item(item_id, produto_id)

    def _calcular_total_alocado(self, item_id: str, produto_id: str) -> float:
        """Calcula total já alocado para um item+produto."""
        return self._alocacao_estoque._calcular_total_alocado(item_id, produto_id)

    def _calcular_saldo_a_processar(self, item_id: str, produto_id: str, quantidade_necessaria: float) -> float:
        """Calcula quanto ainda precisa ser processado."""
        return self._alocacao_estoque._calcular_saldo_a_processar(item_id, produto_id, quantidade_necessaria)

    def _verificar_alocacao_existente(self, correlation_id: str) -> bool:
        """Verifica se alocação com correlation_id já existe."""
        return self._alocacao_estoque._verificar_alocacao_existente(correlation_id)

    def processar_alocacao_de_demanda(self, item_id: str, campo: str, incremento: float, user_id: str,
                                      skip_visual_update: bool = False, origem_tipo: Optional[int] = None,
                                      retroactive_date: Optional[str] = None, correlation_id: Optional[str] = None):
        """Processa alocação de estoque com base no estágio de produção."""
        return self._alocacao_estoque.processar_alocacao_de_demanda(
            item_id, campo, incremento, user_id, skip_visual_update,
            origem_tipo, retroactive_date, correlation_id
        )

    def associar_saida_a_demanda(self, demanda_id: str, product_id: str, quantity: float, user_id: str = 'System'):
        """Associa saída de estoque a uma demanda."""
        return self._alocacao_estoque.associar_saida_a_demanda(demanda_id, product_id, quantity, user_id)

    def processar_alocacao_avulsa_otimizado(self, product_id: str, campo: str, quantidade: float,
                                            user_id: str, sincrono: bool = False):
        """Processa alocação avulsa otimizada."""
        return self._alocacao_estoque.processar_alocacao_avulsa_otimizado(
            product_id, campo, quantidade, user_id, sincrono
        )

    def processar_alocacao_de_demanda_otimizado(self, item_id: str, campo: str, incremento: float, user_id: str,
                                               itens_dict: dict, saldos_produtos: dict, boms_produtos: dict,
                                               origem_tipo: Optional[int] = None, retroactive_date: Optional[str] = None,
                                               correlation_id: Optional[str] = None):
        """Versão otimizada de processar_alocacao_de_demanda com dados pré-carregados."""
        return self._alocacao_estoque.processar_alocacao_de_demanda_otimizado(
            item_id, campo, incremento, user_id, itens_dict, saldos_produtos, boms_produtos,
            origem_tipo, retroactive_date, correlation_id
        )

    def _executar_movimentacao_estoque_recursiva(self, item_id, produto_id, quantidade, demanda_id,
                                                  user_id, correlation_id, tipo_operacao, mov_date,
                                                  deve_sair_no_final=True):
        """Executa movimentação de estoque recursiva."""
        return self._alocacao_estoque._executar_movimentacao_estoque_recursiva(
            item_id, produto_id, quantidade, demanda_id, user_id,
            correlation_id, tipo_operacao, mov_date, deve_sair_no_final
        )

    def alocar_producao_automatica(self, produto_id: str, quantidade: float, user_id: str = 'System'):
        """Aloca produção automática para um produto."""
        return self._alocacao_estoque.alocar_producao_automatica(produto_id, quantidade, user_id)

    def get_demandas_ativas_por_item(self, produto_id: str) -> List[Dict[str, Any]]:
        """Busca demandas ativas por item."""
        return self._alocacao_estoque.get_demandas_ativas_por_item(produto_id)

    def get_pending_items_by_miolo(self, miolo_id: str) -> List[Dict[str, Any]]:
        """Busca itens pendentes por miolo."""
        return self._alocacao_estoque.get_pending_items_by_miolo(miolo_id)

    # ========================================================================
    # MÉTODOS FILA (demanda_alocacao.queue)
    # ========================================================================
    
    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento, user_id='System',
                                      correlation_id=None, created_at=None, produto_id=None, forcar_sincrono=False):
        """Agenda processamento de estoque na fila."""
        return self._alocacao_queue.agendar_processamento_estoque(
            demanda_id, item_id, campo, incremento, user_id,
            correlation_id, created_at, produto_id, forcar_sincrono
        )

    def processar_fila_estoque(self, limit=10):
        """Processa tarefas pendentes na fila de processamento de estoque."""
        return self._alocacao_queue.processar_fila_estoque(limit)

    # ========================================================================
    # MÉTODOS WATERFALL (demanda_alocacao.waterfall)
    # ========================================================================
    
    def processar_insumos_por_bom_recursivo(self, produto_id: str, quantidade: float, correlation_id: str,
                                            user_id: str, tipo_operacao: str = 'CONSUMO_BOM',
                                            retroactive_date: Optional[str] = None,
                                            item_id_referencia: str = None,
                                            qtd_a_produzir_forcada: float = None):
        """Processa insumos por BOM recursivo (Waterfall)."""
        return self._alocacao_waterfall.processar_insumos_por_bom_recursivo(
            produto_id, quantidade, correlation_id, user_id, tipo_operacao,
            retroactive_date, item_id_referencia, qtd_a_produzir_forcada
        )

    # ========================================================================
    # MÉTODOS REPORTING DASHBOARD (demanda_reporting.dashboard)
    # ========================================================================
    
    def get_dashboard_summary(self):
        """Obtém sumário do dashboard."""
        return self._reporting_dashboard.get_dashboard_summary()

    def get_prioritized_demandas(self, limit=50):
        """Obtém demandas priorizadas."""
        return self._reporting_dashboard.get_prioritized_demandas(limit)

    def get_demandas_by_status(self, status_list: List[str], product_id=None) -> List[Dict[str, Any]]:
        """Busca demandas por status."""
        return self._reporting_dashboard.get_demandas_by_status(status_list, product_id)

    # ========================================================================
    # MÉTODOS REPORTING KANBAN (demanda_reporting.kanban)
    # ========================================================================
    
    def get_painel_producao_setores(self, setor_id_ou_nome):
        """Retorna dados do painel de produção organizado por setores/colunas Kanban."""
        return self._reporting_kanban.get_painel_producao_setores(setor_id_ou_nome)

    # ========================================================================
    # MÉTODOS REPORTING PRODUCTION (demanda_reporting.production)
    # ========================================================================
    
    def get_daily_production_summary(self):
        """Obtém sumário de produção diária."""
        return self._reporting_production.get_daily_production_summary()

    def get_consolidado_producao(self, trilha=None, sku=None):
        """Obtém consolidado de produção."""
        return self._reporting_production.get_consolidado_producao(trilha, sku)

    def get_consolidado_agrupado_por_sku(self, trilha=None):
        """Obtém consolidado agrupado por SKU."""
        return self._reporting_production.get_consolidado_agrupado_por_sku(trilha)


# Instância singleton para compatibilidade com código existente
demanda_producao_service = DemandaProducaoService()
