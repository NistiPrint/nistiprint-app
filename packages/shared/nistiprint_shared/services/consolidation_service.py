"""
Consolidation Service - Serviço de consolidação de pedidos em demandas.

Este serviço implementa a consolidação por evento: a cada pedido que chega via
webhook, o sistema tenta agrupá-lo em um RASCUNHO existente ou cria um novo.

Fluxo:
1. resolver_modalidade() → canal_modalidade_mapeamento
2. resolver_horario() → regras_logisticas_canal
3. get_regra_consolidacao() → regras_consolidacao_canal
4. buscar_rascunho_compativel() → demandas_producao WHERE status=RASCUNHO
5. adicionar_ao_rascunho() OU criar_rascunho()
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
import logging

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canal_modalidade_service import canal_modalidade_service
from nistiprint_shared.services.regras_consolidacao_service import regras_consolidacao_service
from nistiprint_shared.services.canal_venda_service import canal_venda_service
from nistiprint_shared.services.logistica_coleta_service import logistica_coleta_service
from nistiprint_shared.models.regras_consolidacao_canal import RegrasConsolidacaoCanal
from nistiprint_shared.utils.date_utils import get_now, get_now_iso


logger = logging.getLogger(__name__)


class ConsolidacaoChave:
    """
    Chave de agrupamento para consolidação.
    
    Dois pedidos com a mesma chave podem ser agrupados na mesma demanda.
    """
    
    def __init__(
        self,
        canal_venda_id: int,
        modalidade: str,
        is_flex: bool = False,
        produto_id: Optional[int] = None,
        miolo_id: Optional[int] = None,
        data_entrega: Optional[str] = None
    ):
        self.canal_venda_id = canal_venda_id
        self.modalidade = modalidade
        self.is_flex = is_flex
        self.produto_id = produto_id
        self.miolo_id = miolo_id
        self.data_entrega = data_entrega
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'canal_venda_id': self.canal_venda_id,
            'modalidade': self.modalidade,
            'is_flex': self.is_flex,
            'produto_id': self.produto_id,
            'miolo_id': self.miolo_id,
            'data_entrega': self.data_entrega
        }
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, ConsolidacaoChave):
            return False
        return (
            self.canal_venda_id == other.canal_venda_id and
            self.modalidade == other.modalidade and
            self.is_flex == other.is_flex and
            self.produto_id == other.produto_id and
            self.miolo_id == other.miolo_id and
            self.data_entrega == other.data_entrega
        )
    
    def __repr__(self) -> str:
        return f"ConsolidacaoChave(canal={self.canal_venda_id}, modalidade={self.modalidade})"


class ConsolidationService:
    """
    Serviço de consolidação de pedidos em demandas de produção.
    """
    
    def __init__(self):
        self.demandas_table = supabase_db.table('demandas_producao')
        self.demandas_pedidos_table = supabase_db.table('demandas_pedidos')
        self.pedidos_table = supabase_db.table('pedidos')
        self.pedidos_nao_classificados_table = supabase_db.table('pedidos_nao_classificados')
    
    # ========================================================================
    # MÉTODO PRINCIPAL: Consolidação por Evento
    # ========================================================================
    
    def consolidar_pedido(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        """
        Consolida um pedido em uma demanda de produção.
        
        Chamado imediatamente após upsert_order() no worker.
        
        Args:
            pedido_id: ID do pedido unificado
        
        Returns:
            Demanda criada/atualizada ou None se pedido não classificado
        
        Fluxo:
        1. Buscar pedido e dados do canal
        2. Resolver modalidade (canal_modalidade_mapeamento)
        3. Resolver horário de coleta (regras_logisticas_canal)
        4. Buscar regra de consolidação (regras_consolidacao_canal)
        5. Calcular chave de agrupamento
        6. Buscar rascunho compatível
        7. Adicionar ao rascunho OU criar novo rascunho
        """
        # 1. Buscar pedido
        pedido = self._get_pedido(pedido_id)
        if not pedido:
            logger.error("Pedido %s não encontrado", pedido_id)
            return None
        
        canal_venda_id = pedido.get('canal_venda_id')
        marketplace_integration_id = pedido.get('marketplace_integration_id')
        if not canal_venda_id:
            logger.warning("Pedido %s sem canal_venda_id", pedido_id)
            return None
        
        # 2. Resolver modalidade
        servico_logistico = pedido.get('servico_logistico', '')
        modalidade = self.resolver_modalidade(
            canal_venda_id,
            servico_logistico,
            is_flex=bool(pedido.get('is_flex')),
            fulfillment=bool(pedido.get('fulfillment'))
        )
        
        if not modalidade:
            # Pedido não classificado: entrar em fila de atenção
            logger.warning(
                "Pedido %s não classificado (servico: '%s')",
                pedido_id,
                servico_logistico
            )
            self._sinalizar_pedido_nao_classificado(pedido_id, canal_venda_id, servico_logistico)
            return None
        
        # 3. Resolver horário de coleta
        horario_coleta = self.resolver_horario(
            canal_venda_id=canal_venda_id,
            modalidade=modalidade,
            marketplace_integration_id=marketplace_integration_id,
        )
        
        # 4. Buscar regra de consolidação
        regra = self._get_regra_consolidacao(canal_venda_id, modalidade)
        
        # 5. Calcular chave de agrupamento
        chave = self._calcular_chave(pedido, modalidade, regra)
        
        # 6. Verificar se cria demanda direta (janela = 0)
        if regra.cria_demanda_direta():
            logger.info(
                "Pedido %s: criando demanda direta (janela=0)",
                pedido_id
            )
            return self._criar_demanda_direta(pedido, modalidade, horario_coleta)
        
        # 7. Buscar rascunho compatível
        rascunho = self._buscar_rascunho_compativel(chave)
        
        if rascunho:
            # Adicionar ao rascunho existente
            return self._adicionar_ao_rascunho(rascunho, pedido, regra)
        else:
            # Criar novo rascunho
            return self._criar_rascunho(pedido, modalidade, horario_coleta, chave, regra)
    
    # ========================================================================
    # RESOLUÇÃO DE MODALIDADE E HORÁRIO
    # ========================================================================
    
    def resolver_modalidade(
        self,
        canal_venda_id: int,
        servico_logistico: str,
        is_flex: bool = False,
        fulfillment: bool = False
    ) -> Optional[str]:
        """
        Resolve modalidade logística a partir do servico_logístico.
        
        Args:
            canal_venda_id: ID do canal de venda
            servico_logistico: String do serviço logístico
        
        Returns:
            Modalidade (STANDARD, EXPRESS, FULFILLMENT, RETIRADA) ou None
        """
        # Usar função SQL (mais performático)
        try:
            result = supabase_db.rpc(
                'derivar_modalidade_logistica',
                {
                    'p_canal_venda_id': canal_venda_id,
                    'p_servico_logistico': servico_logistico
                }
            ).execute()
            
            if result.data:
                return result.data
        except Exception as e:
            logger.warning(
                "RPC derivar_modalidade_logistica falhou: %s",
                str(e)
            )
        
        # Fallback: service Python
        return canal_modalidade_service.derivar_modalidade_com_fallback(
            canal_venda_id,
            servico_logistico,
            is_flex=is_flex,
            fulfillment=fulfillment
        )
    
    def resolver_horario(
        self,
        canal_venda_id: int,
        modalidade: str,
        marketplace_integration_id: Optional[int] = None
    ) -> Optional[str]:
        """
        Resolve horário de coleta.
        
        FONTE CANÔNICA:
        1. regras_logisticas_integracao por marketplace_integration_id
        2. None
        
        Args:
            canal_venda_id: ID do canal de venda
            modalidade: Modalidade logística
        
        Returns:
            Horário de coleta (HH:MM) ou None
        """
        contexto = logistica_coleta_service.calcular_contexto_coleta(
            marketplace_integration_id=marketplace_integration_id,
            modalidade=modalidade,
        )
        if not contexto.get("tem_regra"):
            # Fallback apenas para transição: tentar resolver marketplace pelo canal.
            contexto = logistica_coleta_service.resolver_por_canal(
                canal_venda_id=canal_venda_id,
                modalidade=modalidade,
            )
        return contexto.get("proxima_coleta_horario")
    
    # ========================================================================
    # CÁLCULO DE CHAVE E BUSCA DE RASCUNHO
    # ========================================================================
    
    def _calcular_chave(
        self,
        pedido: Dict[str, Any],
        modalidade: str,
        regra: RegrasConsolidacaoCanal
    ) -> ConsolidacaoChave:
        """
        Calcula chave de agrupamento com base nas flags da regra.
        
        Args:
            pedido: Dados do pedido
            modalidade: Modalidade logística
            regra: Regra de consolidação
        
        Returns:
            Chave de consolidação
        """
        return ConsolidacaoChave(
            canal_venda_id=pedido.get('canal_venda_id'),
            modalidade=modalidade,
            is_flex=bool(pedido.get('is_flex')),
            produto_id=pedido.get('produto_id') if regra.agrupar_por_produto else None,
            miolo_id=pedido.get('id_produto_miolo') if regra.agrupar_por_miolo else None,
            data_entrega=pedido.get('data_entrega') or (str(pedido.get('data_limite_envio') or '')).split('T')[0] if regra.agrupar_por_data_entrega else None
        )
    
    def _buscar_rascunho_compativel(
        self,
        chave: ConsolidacaoChave
    ) -> Optional[Dict[str, Any]]:
        """
        Busca rascunho compatível para agrupamento.
        """
        # Construir query dinâmica baseada na chave
        query = self.demandas_table.select('*') \
            .eq('status', 'RASCUNHO') \
            .eq('canal_venda_id', chave.canal_venda_id) \
            .eq('modalidade_logistica', chave.modalidade) \
            .eq('is_flex', chave.is_flex) \
            .gt('rascunho_expira_em', get_now_iso()) \
            .order('rascunho_expira_em', desc=False) \
            .limit(1)
        
        # Adicionar filtros opcionais
        if chave.produto_id:
            query = query.eq('produto_id', chave.produto_id)
        
        # Executar query
        response = query.execute()
        
        if not response.data:
            return None
        
        return response.data[0]
    
    # ========================================================================
    # ADICIONAR AO RASCUNHO / CRIAR RASCUNHO
    # ========================================================================
    
    def _adicionar_ao_rascunho(
        self,
        rascunho: Dict[str, Any],
        pedido: Dict[str, Any],
        regra: RegrasConsolidacaoCanal
    ) -> Optional[Dict[str, Any]]:
        """
        Adiciona pedido a um rascunho existente.
        
        Args:
            rascunho: Dados do rascunho
            pedido: Dados do pedido
            regra: Regra de consolidação
        
        Returns:
            Rascunho atualizado
        """
        demanda_id = rascunho['id']
        pedido_id = pedido['id']
        
        # Verificar se pedido já está vinculado (deduplicação)
        existing = self.demandas_pedidos_table.select('id') \
            .eq('demanda_id', demanda_id) \
            .eq('pedido_id', pedido_id) \
            .execute()
        
        if existing.data:
            logger.debug("Pedido %s já vinculado à demanda %s", pedido_id, demanda_id)
            return rascunho
        
        # Verificar se rascunho foi editado pelo usuário
        editado_pelo_usuario = rascunho.get('editado_pelo_usuario', False)
        adicionado_apos_edicao = editado_pelo_usuario
        
        # Adicionar vínculo N:N
        self.demandas_pedidos_table.insert({
            'demanda_id': demanda_id,
            'pedido_id': pedido_id,
            'adicionado_apos_edicao': adicionado_apos_edicao,
            'adicionado_em': get_now_iso()
        }).execute()
        
        # Calcular quantidade do pedido
        quantidade_pedido = self._calcular_quantidade_pedido(pedido)
        
        # Atualizar rascunho
        update_data = {
            'quantidade': (rascunho.get('quantidade') or 0) + quantidade_pedido,
            # Janela deslizante: reabre prazo a cada pedido
            'rascunho_expira_em': (get_now() + timedelta(hours=regra.janela_agrupamento_horas)).isoformat()
        }
        
        # Sinalização de revisão (Opção A)
        if adicionado_apos_edicao:
            update_data['pedidos_apos_edicao_qtd'] = (rascunho.get('pedidos_apos_edicao_qtd') or 0) + 1
            # requer_revisao será atualizado pelo trigger
        
        # Atualizar data_entrega se for mais urgente
        data_entrega_pedido = pedido.get('data_entrega') or (str(pedido.get('data_limite_envio') or '')).split('T')[0]
        if data_entrega_pedido:
            data_entrega_atual = rascunho.get('data_entrega')
            if not data_entrega_atual or data_entrega_pedido < data_entrega_atual:
                update_data['data_entrega'] = data_entrega_pedido
                # Recalcular categoria temporal
                update_data['categoria_temporal'] = self._calcular_categoria_temporal(
                    data_entrega_pedido,
                    rascunho.get('modalidade_logistica')
                )
        
        # Executar update
        response = self.demandas_table.update(update_data) \
            .eq('id', demanda_id) \
            .execute()
        
        if not response.data:
            logger.error("Falha ao atualizar rascunho %s", demanda_id)
            return rascunho
        
        logger.info(
            "Pedido %s adicionado ao rascunho %s (qtd=%d, apos_edicao=%s)",
            pedido_id,
            demanda_id,
            quantidade_pedido,
            adicionado_apos_edicao
        )
        
        return response.data[0]
    
    def _criar_rascunho(
        self,
        pedido: Dict[str, Any],
        modalidade: str,
        horario_coleta: Optional[str],
        chave: ConsolidacaoChave,
        regra: RegrasConsolidacaoCanal
    ) -> Optional[Dict[str, Any]]:
        """
        Cria novo rascunho para um pedido.
        
        Args:
            pedido: Dados do pedido
            modalidade: Modalidade logística
            horario_coleta: Horário de coleta
            chave: Chave de consolidação
            regra: Regra de consolidação
        
        Returns:
            Rascunho criado
        """
        canal = canal_venda_service.get_by_id(str(pedido.get('canal_venda_id')))
        if not canal:
            logger.error("Canal %s não encontrado", pedido.get('canal_venda_id'))
            return None
        
        # Calcular categoria temporal
        data_entrega = pedido.get('data_entrega') or pedido.get('data_limite_envio', '').split('T')[0]
        categoria_temporal = self._calcular_categoria_temporal(data_entrega, modalidade)
        
        # Calcular quantidade
        quantidade = self._calcular_quantidade_pedido(pedido)
        
        # Criar demanda
        demanda_id = f"DEM-{get_now().strftime('%Y%m%d%H%M%S')}-{pedido.get('canal_venda_id')}"
        demanda_payload = {
            'demanda_id': demanda_id,
            'status': 'RASCUNHO',
            'descricao': f"Rascunho {canal.get('nome', 'Canal')} - {modalidade} - {data_entrega or 'Sem data'}",
            'canal_venda_id': pedido.get('canal_venda_id'),
            'produto_id': chave.produto_id,
            'modalidade_logistica': modalidade,
            'horario_coleta': horario_coleta,
            'is_flex': bool(pedido.get('is_flex')),
            'fulfillment': bool(pedido.get('fulfillment')),
            'data_entrega': data_entrega,
            'quantidade': quantidade,
            'rascunho_expira_em': (get_now() + timedelta(hours=regra.janela_agrupamento_horas)).isoformat(),
            'categoria_temporal': categoria_temporal,
            'editado_pelo_usuario': False,
            'pedidos_apos_edicao_qtd': 0,
            'requer_revisao': False,
            'origem_demanda': 'AUTOMATICA',  # ✅ Rascunho criado automaticamente
            'created_at': get_now_iso(),
            'updated_at': get_now_iso()
        }
        
        # Inserir demanda
        response = self.demandas_table.insert(demanda_payload).execute()
        
        if not response.data:
            logger.error("Falha ao criar rascunho")
            return None
        
        demanda_id = response.data[0]['id']
        
        # Vincular pedido
        self.demandas_pedidos_table.insert({
            'demanda_id': demanda_id,
            'pedido_id': pedido.get('id'),
            'adicionado_apos_edicao': False,
            'adicionado_em': get_now_iso()
        }).execute()
        
        logger.info(
            "Rascunho %s criado para pedido %s (canal=%s, modalidade=%s)",
            demanda_id,
            pedido.get('id'),
            pedido.get('canal_venda_id'),
            modalidade
        )
        
        return response.data[0]
    
    def _criar_demanda_direta(
        self,
        pedido: Dict[str, Any],
        modalidade: str,
        horario_coleta: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Cria demanda direta (sem rascunho) para casos com janela=0.
        
        Args:
            pedido: Dados do pedido
            modalidade: Modalidade logística
            horario_coleta: Horário de coleta
        
        Returns:
            Demanda criada
        """
        canal = canal_venda_service.get_by_id(str(pedido.get('canal_venda_id')))
        if not canal:
            logger.error("Canal %s não encontrado", pedido.get('canal_venda_id'))
            return None
        
        data_entrega = pedido.get('data_entrega') or pedido.get('data_limite_envio', '').split('T')[0]
        categoria_temporal = self._calcular_categoria_temporal(data_entrega, modalidade)
        quantidade = self._calcular_quantidade_pedido(pedido)
        
        demanda_id = f"DEM-{get_now().strftime('%Y%m%d%H%M%S')}-{pedido.get('canal_venda_id')}"
        demanda_payload = {
            'demanda_id': demanda_id,
            'status': 'AGUARDANDO',  # Já publicada
            'descricao': f"Demanda {canal.get('nome', 'Canal')} - {modalidade} - {pedido.get('numero_pedido', 'N/A')}",
            'canal_venda_id': pedido.get('canal_venda_id'),
            'produto_id': pedido.get('produto_id'),
            'modalidade_logistica': modalidade,
            'horario_coleta': horario_coleta,
            'is_flex': bool(pedido.get('is_flex')),
            'fulfillment': bool(pedido.get('fulfillment')),
            'data_entrega': data_entrega,
            'quantidade': quantidade,
            'categoria_temporal': categoria_temporal,
            'pedido_numero': pedido.get('numero_pedido'),
            'pedido_id': pedido.get('id'),
            'origem_demanda': 'AUTOMATICA',  # ✅ Demanda criada automaticamente
            'publicado_em': get_now_iso(),
            'created_at': get_now_iso(),
            'updated_at': get_now_iso()
        }
        
        response = self.demandas_table.insert(demanda_payload).execute()
        
        if not response.data:
            logger.error("Falha ao criar demanda direta")
            return None
        
        demanda_id = response.data[0]['id']
        
        # Vincular pedido
        self.demandas_pedidos_table.insert({
            'demanda_id': demanda_id,
            'pedido_id': pedido.get('id'),
            'adicionado_apos_edicao': False,
            'adicionado_em': get_now_iso()
        }).execute()
        
        logger.info(
            "Demanda direta %s criada para pedido %s (janela=0)",
            demanda_id,
            pedido.get('id')
        )
        
        return response.data[0]
    
    # ========================================================================
    # UTILITÁRIOS
    # ========================================================================
    
    def _get_pedido(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        """Busca pedido por ID."""
        response = self.pedidos_table.select('*') \
            .eq('id', pedido_id) \
            .maybe_single() \
            .execute()
        return response.data
    
    def _get_regra_consolidacao(
        self,
        canal_venda_id: int,
        modalidade: str
    ) -> RegrasConsolidacaoCanal:
        """Busca regra de consolidação."""
        return regras_consolidacao_service.get_regra_para_pedido(canal_venda_id, modalidade)
    
    def _calcular_quantidade_pedido(self, pedido: Dict[str, Any]) -> int:
        """Calcula quantidade total de itens do pedido."""
        try:
            response = supabase_db.table('itens_pedido') \
                .select('quantidade') \
                .eq('pedido_id', pedido.get('id')) \
                .execute()
            total = sum(float(item.get('quantidade') or 0) for item in (response.data or []))
            return int(total) if total > 0 else 1
        except Exception as e:
            logger.warning("Falha ao calcular quantidade do pedido %s: %s", pedido.get('id'), e)
            return 1
    
    def _calcular_categoria_temporal(
        self,
        data_entrega: Optional[str],
        modalidade: str
    ) -> str:
        """
        Calcula categoria temporal (URGENTE, HOJE, AMANHA, FUTURO).
        
        Args:
            data_entrega: Data de entrega (YYYY-MM-DD)
            modalidade: Modalidade logística
        
        Returns:
            Categoria temporal
        """
        if not data_entrega:
            return 'FUTURO'
        
        try:
            from datetime import date
            
            data_entrega_date = date.fromisoformat(data_entrega)
            hoje = date.today()
            amanha = hoje + timedelta(days=1)
            
            if data_entrega_date == hoje:
                return 'HOJE'
            elif data_entrega_date == amanha:
                return 'AMANHA'
            elif data_entrega_date < hoje:
                return 'URGENTE'
            else:
                return 'FUTURO'
        except Exception:
            return 'FUTURO'
    
    def _sinalizar_pedido_nao_classificado(
        self,
        pedido_id: int,
        canal_venda_id: int,
        servico_logistico: str
    ):
        """
        Sinaliza pedido não classificado para atenção manual.
        
        Args:
            pedido_id: ID do pedido
            canal_venda_id: ID do canal
            servico_logistico: Serviço logístico recebido
        """
        try:
            self.pedidos_nao_classificados_table.insert({
                'pedido_id': pedido_id,
                'canal_venda_id': canal_venda_id,
                'servico_logistico_recebido': servico_logistico
            }).execute()
        except Exception as e:
            logger.error(
                "Falha ao sinalizar pedido não classificado %s: %s",
                pedido_id,
                str(e)
            )


# Singleton
consolidation_service = ConsolidationService()
