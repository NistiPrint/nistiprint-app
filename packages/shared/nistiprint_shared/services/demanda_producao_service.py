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
    def create_from_order(self, order_data: Dict[str, Any], user_id='System', **kwargs) -> Dict[str, Any]:
        """
        Gera uma demanda de produção a partir de um pedido unificado.
        Aceita is_flex, modalidade_logistica e canal_venda_id via kwargs.
        """
        # 1. Resolver metadados básicos (explícitos ou via DB)
        is_flex = kwargs.get('is_flex')
        modalidade = kwargs.get('modalidade_logistica')
        canal_venda_id = kwargs.get('canal_venda_id')

        # Determine Platform and ID based on payload
        # Priority: order_sn (Shopee), order_id (ML), numeroLoja (Bling)
        plataforma = order_data.get('plataforma', 'Bling')
        
        external_id = None
        if 'order_sn' in order_data:
            external_id = str(order_data['order_sn'])
            if 'plataforma' not in order_data: plataforma = 'Shopee'
        elif 'order_id' in order_data:
            external_id = str(order_data['order_id'])
            if 'plataforma' not in order_data: plataforma = 'MercadoLivre'
        elif 'AmazonOrderId' in order_data:
            external_id = str(order_data['AmazonOrderId'])
            if 'plataforma' not in order_data: plataforma = 'Amazon'
        else:
            # Fallback to Bling standard
            external_id = str(order_data.get('numeroLoja') or order_data.get('numero'))

        if not external_id:
            raise ValueError("Pedido sem número identificador (numeroLoja, order_sn, etc)")

        # Se não vieram via kwargs, tenta ler do banco 'pedidos'
        if is_flex is None or modalidade is None or canal_venda_id is None:
            try:
                pedido_db = supabase_db.table('pedidos')\
                    .select('is_flex, modalidade_logistica, canal_venda_id')\
                    .eq('codigo_pedido_externo', external_id)\
                    .maybe_single().execute().data
                if pedido_db:
                    if is_flex is None: is_flex = pedido_db.get('is_flex')
                    if modalidade is None: modalidade = pedido_db.get('modalidade_logistica')
                    if canal_venda_id is None: canal_venda_id = pedido_db.get('canal_venda_id')
            except Exception as e:
                print(f"⚠️ Erro ao buscar metadados do pedido {external_id} no banco: {e}")

        # Prepare list for deduplication check
        items_for_check = []
        for item in order_data.get('itens', []):
            qty = int(float(item.get('quantidade', 1)))
            sku = str(item.get('codigo') or item.get('sku') or '')
            # Try to get specific item ID if available (e.g. from Shopee line item id)
            item_ext_id = str(item.get('id') or item.get('order_item_id') or sku)
            
            items_for_check.append({
                'sku_externo': sku,
                'item_externo_id': item_ext_id,
                'quantidade': qty
            })

        orders_list = [{
            'pedido_externo_id': external_id,
            'items': items_for_check,
            'plataforma': plataforma
        }]

        # 1. Filter Deduplication
        filtered_orders = order_tracker_service.filter_processed_items(orders_list, plataforma)
        if not filtered_orders:
            # All items processed
            existing = self.demandas_table.select("id").eq('demanda_id', external_id).execute()
            if existing.data:
                return self.get_demanda_with_itens(existing.data[0]['id'])
            # If no demand exists but items are processed, maybe they were processed in a consolidated batch?
            # Return None to indicate no *new* demand created.
            return None

        # 2. Process Remaining Items
        # We take the first order from filtered list (since we passed only one)
        remaining_items = filtered_orders[0]['items']
        
        # Prepare content for new demand
        contato_nome = order_data.get('contato', {}).get('nome', 'Cliente Desconhecido')
        nome_demanda = f"Pedido {order_data.get('numero') or external_id} - {contato_nome}"
        
        data_entrega = order_data.get('dataPrevista') or order_data.get('data') or get_now().strftime('%Y-%m-%d')
        if isinstance(data_entrega, str) and 'T' in data_entrega:
            data_entrega = data_entrega.split('T')[0]

        itens_demanda = []
        
        # We iterate over original items to preserve metadata (desc), but check against remaining
        # OR just use remaining items if we carried enough metadata.
        # Since 'items_for_check' was lightweight, we should match back to full 'order_data' items
        # or simply rely on the fact that if it's in 'remaining', we process it.
        # But 'remaining' lacks description if we didn't put it in 'items_for_check'.
        
        # Better approach: map remaining item keys to allow lookup
        remaining_map = {(i['sku_externo'], i['item_externo_id']): i['quantidade'] for i in remaining_items}
        
        for item in order_data.get('itens', []):
            sku = str(item.get('codigo') or item.get('sku') or '')
            item_ext_id = str(item.get('id') or item.get('order_item_id') or sku)
            
            key = (sku, item_ext_id)
            if key in remaining_map:
                qty_to_process = remaining_map[key]
                
                # Resolve Variation
                nome_externo = item.get('descricao') or item.get('name')
                resolved_prod = product_service.resolve_variation(sku, plataforma, nome_externo)
                
                prod_id = resolved_prod['id'] if resolved_prod else None
                
                itens_demanda.append({
                    'sku': sku,
                    'descricao': nome_externo,
                    'quantidade': qty_to_process,
                    'produto_id': prod_id,
                    # Pass external ID to persist in tracking later
                    '_item_externo_id': item_ext_id 
                })

        if not itens_demanda:
            return None

        observacoes = f"Importado automaticamente. ID Externo: {external_id}"
        if 'observacoes' in order_data:
             observacoes += f"\nObs Pedido: {order_data['observacoes']}"

        # 3. Create Demand
        new_demanda = self.criar_demanda_direta(
            nome_demanda=nome_demanda,
            canal_venda_id=None,
            data_entrega_str=data_entrega,
            lista_de_itens=itens_demanda,
            demanda_id=external_id, # Can allow duplicates in ID if we suffix? No, demanda_id constraint.
            # If partial, maybe suffix? "ID-Part2"?
            # Current logic: 'demanda_id' unique.
            # If we are processing partial, it means previous demand likely exists or items were processed in OTHER demand.
            # If items processed in *other* demand (Consolidation), we are creating a NEW demand for the *remainder*.
            # So we might need a unique ID for this new partial demand.
            # Let's append timestamp or uuid if conflict likely?
            # Or trust UUID generation inside `criar_demanda_direta` if we pass None?
            # But we passed external_id as `demanda_id`.
            # Let's try to pass external_id. If conflict, `criar_demanda_direta` might fail or we should handle.
            # Actually `create_from_order` logic at start checks existing.
            # If we are here, we decided to create new. So we should probably allow a unique ID if original is taken.
            # Let's pass `demanda_id=None` to auto-generate UUID for the *Internal* ID,
            # but store external_id in `pedido_numero` field for reference.
            pedido_numero=str(order_data.get('numero') or external_id),
            observacoes=observacoes,
            user_id=user_id,
            tipo_demanda='PLATAFORMA'  # Consolidated orders are always 'PLATAFORMA' type
        )

        # 4. Register Processed Items
        # Reconstruct orders_list with the items we actually processed (itens_demanda)
        # to ensure tracker is accurate on what was done.
        
        items_processed_for_tracker = []
        for iditem in itens_demanda:
            items_processed_for_tracker.append({
                'sku_externo': iditem['sku'],
                'item_externo_id': iditem.get('_item_externo_id'),
                'quantidade': iditem['quantidade'],
                'produto_id': iditem['produto_id']
            })
            
        final_orders_list = [{
            'pedido_externo_id': external_id,
            'plataforma': plataforma,
            'items': items_processed_for_tracker
        }]
        
        if new_demanda:
            order_tracker_service.register_processed_items(new_demanda['id'], final_orders_list, plataforma)

        return new_demanda

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
        """Calcula e executa reserva de estoque seguindo lógica Waterfall (V2)."""
        return self._alocacao_estoque.processar_reserva_inteligente_v2(demanda_id, itens_payload, user_id)

    def _reservar_recursivo(self, produto_id, quantidade, deposito_id, report_list, nivel=0):
        """Motor recursivo de reserva (Deprecado - use V2 em alocacao_estoque)."""
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

    def registrar_producao_incremental(self, demanda_id: str, item_id: str, producao_incremental: Dict[str, float], 
                                       user_id: str = 'System', origem_tipo: int = 1,
                                       retroactive_date: str = None, correlation_id: str = None) -> Dict[str, Any]:
        """
        Registra produção incremental para um item de demanda.
        
        Args:
            demanda_id: ID da demanda
            item_id: ID do item
            producao_incremental: Dicionário com campos e valores para atualizar (ex: {'capas_impressas_qtd': 1})
            user_id: ID do usuário
            origem_tipo: Tipo de origem (1=incremento, 2=estorno)
            retroactive_date: Data retroativa para a produção
            correlation_id: ID de correlação para rastreamento
            
        Returns:
            Item atualizado
        """
        return self._items.atualizar_progresso_item(
            demanda_id, item_id, producao_incremental, user_id
        )

    def registrar_producao_lote(self, demanda_id: str, updates: List[Dict[str, Any]], user_id: str = 'System',
                                origem_tipo: int = 1, retroactive_date: str = None, 
                                correlation_id: str = None) -> Dict[str, Any]:
        """
        Registra produção incremental para múltiplos itens de uma demanda de uma vez.
        
        Args:
            demanda_id: ID da demanda
            updates: Lista de dicionários contendo 'item_id' e 'producao_incremental'
            user_id: ID do usuário
            origem_tipo: Tipo de origem (1=incremento, 2=estorno)
            retroactive_date: Data retroativa para a produção
            correlation_id: ID de correlação para rastreamento
            
        Returns:
            Dicionário com 'results' (lista de itens atualizados) e 'count' (quantidade processada)
        """
        results = []
        for update in updates:
            item_id = update.get('item_id')
            producao_incremental = update.get('producao_incremental', {})
            
            if not item_id or not producao_incremental:
                continue
                
            try:
                updated_item = self.registrar_producao_incremental(
                    demanda_id, item_id, producao_incremental, user_id,
                    origem_tipo=origem_tipo,
                    retroactive_date=retroactive_date,
                    correlation_id=correlation_id
                )
                results.append(updated_item)
            except Exception as e:
                print(f"ERROR processing item {item_id} in batch: {e}")
                raise
        
        return {
            'results': results,
            'count': len(results)
        }

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

    def registrar_retirada_expedicao(self, demanda_id: str, item_id: str, quantidade: int, user_id: str = 'System') -> Dict[str, Any]:
        """
        Registra a retirada de capas e miolos na expedição para um item de demanda.

        Atualiza simultaneamente os campos expedicao_capas_retiradas_qtd e expedicao_miolos_retirados_qtd,
        pois na expedição o produto final (capa + miolo) é retirado junto.

        Args:
            demanda_id: ID da demanda
            item_id: ID do item da demanda
            quantidade: Quantidade a retirar (unidades completas capa+miolo)
            user_id: ID do usuário

        Returns:
            Item atualizado com os novos valores de expedição
        """
        return self._items.registrar_retirada_expedicao(demanda_id, item_id, quantidade, user_id)

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
    
    def get_stock_history_for_item(self, item_id: int) -> List[Dict[str, Any]]:
        """Busca o histórico de reconciliação de estoque de um item de demanda."""
        response = supabase_db.table('demanda_estoque_processado').select('*').eq('item_id', item_id).order('created_at', desc=True).execute()
        return response.data

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
