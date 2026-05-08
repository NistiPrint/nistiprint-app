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
        """
        Estorna finalização de um item (alias de reverter_finalizacao_item).
        O parâmetro `quantidade` é ignorado: a reversão é total no fluxo atual.
        """
        return self._items.reverter_finalizacao_item(demanda_id, item_id, user_id)

    def atualizar_progresso_item(self, demanda_id: str, item_id: str,
                                 quantities_to_update: Dict[str, float],
                                 user_id: str = 'System'):
        """Atualiza o progresso (capas/miolos) de um item da demanda."""
        return self._items.atualizar_progresso_item(demanda_id, item_id, quantities_to_update, user_id)

    def reverter_finalizacao_item(self, demanda_id, item_id, user_id='System'):
        """Reverte a finalização (total) de um item, voltando o status para 'Em Andamento'."""
        return self._items.reverter_finalizacao_item(demanda_id, item_id, user_id)

    def registrar_saida_item_distribuida(self, distributions, product_id, user_id='System', transaction=None):
        """
        Registra a saída distribuída de um produto entre múltiplos itens de demanda
        (usado pela ControleProducaoPage ao alocar estoque para várias demandas).
        """
        return self._items.registrar_saida_item_distribuida(distributions, product_id, user_id, transaction)

    def registrar_retirada_expedicao(self, demanda_id: str, item_id: str, quantidade: int,
                                     user_id: str = 'System') -> Dict[str, Any]:
        """Registra a retirada pela expedição (Setor 4)."""
        return self._items.registrar_retirada_expedicao(demanda_id, item_id, quantidade, user_id)

    # ========================================================================
    # MÉTODOS STATUS (demanda.status)
    # ========================================================================

    def transicionar_status(self, demanda_id: str, novo_status: str, user_id: str = 'System') -> Dict[str, Any]:
        """Altera o status de uma demanda."""
        return self._status.transicionar_status(demanda_id, novo_status, user_id)

    def auto_atualizar_status_demanda(self, demanda_id: str) -> str:
        """Avalia e atualiza automaticamente o status da demanda com base nos itens."""
        return self._status.auto_atualizar_status_demanda(demanda_id)

    def finalizar_demanda_completa(self, demanda_id, user_id='System'):
        """Finaliza a demanda inteira (todos os itens marcados como concluídos)."""
        return self._status.finalizar_demanda_completa(demanda_id, user_id)

    def publicar_demanda(self, demanda_id: str, user_id: str = 'System') -> Dict[str, Any]:
        """
        Publica uma demanda (transiciona para 'EM_PRODUCAO').
        Wrapper sobre transicionar_status mantendo compatibilidade com a rota /publicar.
        """
        return self._status.transicionar_status(demanda_id, 'EM_PRODUCAO', user_id)

    # ========================================================================
    # MÉTODOS COLLECTIONS (demanda.collections)
    # ========================================================================

    def registrar_coleta(self, demanda_id: str, quantidade: int, ponto_coleta_id: Optional[int] = None,
                         observacoes: Optional[str] = None, user_id: str = 'System') -> Dict[str, Any]:
        """
        Registra a coleta (física/saída) de uma quantidade da demanda.
        Atualmente delega para registrar_coleta_parcial; ponto_coleta_id e observacoes
        ainda não são persistidos (TODO: estender o método parcial para suportá-los).
        """
        if ponto_coleta_id or observacoes:
            logger.info(
                f"registrar_coleta: ponto_coleta_id={ponto_coleta_id} e/ou observacoes ignorados "
                "(não suportados em registrar_coleta_parcial)"
            )
        return self._collections.registrar_coleta_parcial(demanda_id, quantidade, user_id)

    def registrar_saida_item_producao(self, item_id: int, quantidade: int, user_id: str = 'System') -> Dict[str, Any]:
        """
        Registra a saída física de unidades produzidas de um item.
        Implementado via registrar_retirada_expedicao (busca demanda_id pelo item).
        """
        resp = supabase_db.execute_with_retry(
            supabase_db.table('itens_demanda').select('demanda_id').eq('id', item_id).limit(1)
        )
        if not resp.data:
            raise ValueError(f"Item {item_id} não encontrado")
        demanda_id = resp.data[0]['demanda_id']
        return self._items.registrar_retirada_expedicao(demanda_id, item_id, quantidade, user_id)

    def get_coletas_da_demanda(self, demanda_id: str) -> List[Dict[str, Any]]:
        """Retorna o histórico de coletas registradas para uma demanda."""
        return self._collections.get_coletas_da_demanda(demanda_id)

    def get_historico_coletas_global(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Retorna o histórico global de coletas (limite configurável)."""
        return self._collections.get_historico_coletas_global(limit)

    def marcar_como_coletado(self, demanda_id, user_id='System'):
        """Marca uma demanda como coletada (consome saldo restante)."""
        return self._collections.marcar_como_coletado(demanda_id, user_id)

    def registrar_coleta_parcial(self, demanda_id: str, quantidade_coletar: int,
                                 user_id: str = 'System') -> Dict[str, Any]:
        """Registra coleta parcial de uma demanda."""
        return self._collections.registrar_coleta_parcial(demanda_id, quantidade_coletar, user_id)

    def marcar_lote_como_coletado(self, demanda_ids, user_id='System'):
        """Marca múltiplas demandas como coletadas em lote."""
        return self._collections.marcar_lote_como_coletado(demanda_ids, user_id)

    # ========================================================================
    # MÉTODOS ALOCAÇÃO ESTOQUE (demanda_alocacao.*)
    # ========================================================================

    def processar_reserva_inteligente(self, demanda_id, itens_payload, user_id):
        """
        Calcula e executa reserva de estoque para uma demanda.
        Delega para processar_alocacao_de_demanda no serviço de alocação.
        """
        return self._alocacao_estoque.processar_alocacao_de_demanda(demanda_id, itens_payload, user_id)

    def processar_fila_estoque(self, limit=10):
        """Processa a fila de tarefas de estoque."""
        return self._alocacao_estoque.processar_fila_estoque(limit=limit)

    def processar_alocacao_avulsa_otimizado(self, product_id, campo, quantidade, user_id, sincrono=False):
        """
        Processa alocação avulsa (entrada de produção via ControleProducaoPage).
        Delega para o serviço especializado de alocação de estoque.
        """
        return self._alocacao_estoque.processar_alocacao_avulsa_otimizado(
            product_id, campo, quantidade, user_id, sincrono
        )

    def agendar_processamento_estoque(self, demanda_id, item_id, campo, incremento,
                                      user_id='System', correlation_id=None,
                                      created_at=None, produto_id=None,
                                      forcar_sincrono=False):
        """Agenda processamento de estoque na fila legada (compatibilidade)."""
        return self._alocacao_estoque.agendar_processamento_estoque(
            demanda_id, item_id, campo, incremento, user_id,
            correlation_id, created_at, produto_id, forcar_sincrono
        )

    def associar_saida_a_demanda(self, demanda_id: str, product_id: str, quantity: int,
                                 user_id: str = 'System') -> Dict[str, Any]:
        """
        Associa uma saída de estoque (de um produto intermediário) a um item de demanda.
        Encontra o item da demanda que tem o produto e incrementa a coluna de pool
        correspondente (capas_impressas_qtd / capas_produzidas_qtd / miolos_prontos_retirada_qtd).
        Delega o consumo de estoque para o motor de reconciliação via registrar_producao_incremental.
        """
        # Localiza o item da demanda associado ao produto
        itens_table = supabase_db.table('itens_demanda')
        # Busca por produto_id direto (capa) ou id_produto_miolo (miolo)
        resp_capa = supabase_db.execute_with_retry(
            itens_table.select('*').eq('demanda_id', demanda_id).eq('produto_id', product_id).limit(1)
        )
        item = resp_capa.data[0] if resp_capa.data else None
        campo = None
        if item:
            campo = 'capas_produzidas_qtd'  # default p/ produto principal de capa
        else:
            resp_miolo = supabase_db.execute_with_retry(
                itens_table.select('*').eq('demanda_id', demanda_id).eq('id_produto_miolo', product_id).limit(1)
            )
            item = resp_miolo.data[0] if resp_miolo.data else None
            if item:
                campo = 'miolos_prontos_retirada_qtd'

        if not item or not campo:
            logger.warning(
                f"associar_saida_a_demanda: item não encontrado para produto {product_id} "
                f"na demanda {demanda_id}"
            )
            return {'success': False, 'message': 'Item não encontrado'}

        # Reaproveita registrar_producao_incremental para passar pelo motor
        return self._items.registrar_producao_incremental(
            demanda_id=demanda_id,
            item_id=item['id'],
            producao_incremental={campo: quantity},
            user_id=user_id,
            origem_tipo=2,  # 2 = saída avulsa associada
        )

    # ========================================================================
    # MÉTODOS REPORTING (demanda_reporting.*)
    # ========================================================================

    def get_demandas_by_status(self, status_list, product_id=None) -> List[Dict[str, Any]]:
        """
        Busca demandas por status (uma string ou lista). Aceita filtro opcional por produto.
        Delega para o serviço de reporting/dashboard.
        """
        return self._report_dashboard.get_demandas_by_status(status_list, product_id=product_id)

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Obtém resumo consolidado de produção para a lista de demandas."""
        return self._report_production.get_daily_production_summary()

    def get_kanban_data(self, setor_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Obtém dados para o quadro Kanban (alias de get_painel_producao_setores)."""
        painel = self._report_kanban.get_painel_producao_setores(setor_id)
        # Manter retorno List para compatibilidade legada
        if isinstance(painel, dict):
            return painel.get('itens') or painel.get('demandas') or []
        return painel or []

    def get_painel_producao_setores(self, setor_id_ou_nome: Optional[int] = None) -> Dict[str, Any]:
        """Obtém dados do painel de produção organizado por setores/colunas Kanban."""
        return self._report_kanban.get_painel_producao_setores(setor_id_ou_nome)

    def get_daily_production_summary(self) -> Dict[str, Any]:
        """Obtém resumo diário de produção consolidado."""
        return self._report_production.get_daily_production_summary()

    def get_demandas_consolidadas(self, data_inicio: str, data_fim: str) -> List[Dict[str, Any]]:
        """
        Obtém demandas consolidadas para relatório no intervalo de datas.
        Atualmente derivado de get_all_demandas + filtro por data_entrega
        (TODO: implementar versão otimizada em demanda_reporting/production.py).
        """
        try:
            todas = self._report_production.get_all_demandas()
            return [
                d for d in todas
                if data_inicio <= (d.get('data_entrega') or '') <= data_fim
            ]
        except Exception as e:
            logger.error(f"get_demandas_consolidadas falhou: {e}")
            return []

    def get_consolidado_producao(self, trilha=None, sku=None) -> Dict[str, Any]:
        """Consolidado de produção (totais por produto/trilha)."""
        return self._report_production.get_consolidado_producao(trilha=trilha, sku=sku)

    def get_consolidado_agrupado_por_sku(self, trilha=None) -> Dict[str, Any]:
        """Consolidado de produção agrupado por SKU."""
        return self._report_production.get_consolidado_agrupado_por_sku(trilha=trilha)

    def get_prioritized_demandas(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Demandas priorizadas (não concluídas), ordenadas por critérios de prioridade."""
        return self._report_dashboard.get_prioritized_demandas(limit=limit)

    def get_demandas_ativas_por_item(self, produto_id, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Lista demandas em status ativos que contêm o produto informado.
        Wrapper sobre get_demandas_by_status com filtro por produto.
        """
        return self._report_dashboard.get_demandas_by_status(
            ['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'],
            product_id=produto_id,
        )

    def get_pending_items_by_miolo(self, miolo_id) -> List[Dict[str, Any]]:
        """
        Lista demandas ativas que tenham itens com o miolo informado, retornando
        os itens pendentes de cada uma.
        Construído sobre get_demandas_by_status + get_items_for_multiple_demandas.
        """
        try:
            demandas_ativas = self._report_dashboard.get_demandas_by_status(
                ['AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL']
            )
            if not demandas_ativas:
                return []

            demanda_ids = [str(d['id']) for d in demandas_ativas]
            itens_map = self._core.get_items_for_multiple_demandas(demanda_ids)

            resultado = []
            for demanda in demandas_ativas:
                itens = itens_map.get(str(demanda['id']), [])
                itens_filtrados = [
                    i for i in itens
                    if str(i.get('id_produto_miolo')) == str(miolo_id)
                    and (i.get('miolos_prontos_retirada_qtd') or 0) < (i.get('quantidade_total') or 0)
                ]
                if itens_filtrados:
                    resultado.append({**demanda, 'itens_pendentes': itens_filtrados})
            return resultado
        except Exception as e:
            logger.error(f"get_pending_items_by_miolo({miolo_id}) falhou: {e}")
            return []

    def get_stock_history_for_item(self, item_id) -> List[Dict[str, Any]]:
        """
        Histórico de estoque de um item de demanda específico.
        Lê o ledger 'demanda_estoque_processado' (registrado pelo motor de reconciliação)
        e retorna em ordem cronológica reversa.
        """
        try:
            response = supabase_db.execute_with_retry(
                supabase_db.table('demanda_estoque_processado')
                .select('*')
                .eq('item_id', item_id)
                .order('created_at', desc=True)
                .limit(500)
            )
            return response.data or []
        except Exception as e:
            logger.error(f"get_stock_history_for_item({item_id}) falhou: {e}")
            return []


# Instância única singleton
demanda_producao_service = DemandaProducaoService()
