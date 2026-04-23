"""
Regras Consolidacao Service - Serviço para configuração de consolidação de pedidos.

Este serviço gerencia as regras de consolidação de pedidos em demandas de produção.

Funcionalidades:
    - Buscar regras de consolidação por canal
    - CRUD de regras
    - Verificar se pedidos devem ser agrupados
    - Determinar política de consolidação
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.regras_consolidacao_canal import RegrasConsolidacaoCanal


logger = logging.getLogger(__name__)


class RegrasConsolidacaoService:
    """
    Serviço para gestão de regras de consolidação de pedidos.
    """
    
    def __init__(self):
        self.table = supabase_db.table('regras_consolidacao_canal')
    
    # ========================================================================
    # MÉTODOS DE CONSULTA (CORE)
    # ========================================================================
    
    def get_regras_canal(
        self,
        canal_venda_id: Optional[int] = None,
        modalidade: Optional[str] = None
    ) -> Optional[RegrasConsolidacaoCanal]:
        """
        Busca regras de consolidação para um canal e modalidade.
        
        Args:
            canal_venda_id: ID do canal de venda (None = buscar regra global)
            modalidade: Modalidade logística (None = todas)
        
        Returns:
            Regras de consolidação ou None
        
        Prioridade:
        1. Regra específica para (canal, modalidade)
        2. Regra do canal (modalidade NULL)
        3. Regra global (canal NULL, modalidade NULL)
        4. None (usa defaults hardcoded)
        """
        # Tentar via função SQL
        try:
            result = supabase_db.rpc(
                'get_regras_consolidacao_canal',
                {
                    'p_canal_venda_id': canal_venda_id,
                    'p_modalidade': modalidade
                }
            ).execute()
            
            if result.data:
                # Retorna primeiro registro (já ordenado pela função)
                return RegrasConsolidacaoCanal.from_dict(result.data[0])
        except Exception as e:
            logger.warning(
                "RPC get_regras_consolidacao_canal falhou: %s. Fallback para Python.",
                str(e)
            )
        
        # Fallback: implementação Python
        return self._get_regras_canal_python(canal_venda_id, modalidade)
    
    def _get_regras_canal_python(
        self,
        canal_venda_id: Optional[int] = None,
        modalidade: Optional[str] = None
    ) -> Optional[RegrasConsolidacaoCanal]:
        """
        Implementação Python de busca de regras (fallback).
        
        Prioridade:
        1. (canal, modalidade)
        2. (canal, NULL)
        3. (NULL, NULL) - global
        """
        # 1. Buscar regra específica (canal, modalidade)
        if canal_venda_id and modalidade:
            response = self.table.select('*') \
                .eq('canal_venda_id', canal_venda_id) \
                .eq('modalidade', modalidade) \
                .eq('ativo', True) \
                .execute()
            
            if response.data:
                return RegrasConsolidacaoCanal.from_dict(response.data[0])
        
        # 2. Buscar regra do canal (modalidade NULL)
        if canal_venda_id:
            response = self.table.select('*') \
                .eq('canal_venda_id', canal_venda_id) \
                .is_('modalidade', None) \
                .eq('ativo', True) \
                .execute()
            
            if response.data:
                return RegrasConsolidacaoCanal.from_dict(response.data[0])
        
        # 3. Buscar regra global (canal NULL, modalidade NULL)
        response = self.table.select('*') \
            .is_('canal_venda_id', None) \
            .is_('modalidade', None) \
            .eq('ativo', True) \
            .execute()
        
        if response.data:
            return RegrasConsolidacaoCanal.from_dict(response.data[0])
        
        return None
    
    def get_regras_ou_defaults(
        self,
        canal_venda_id: Optional[int] = None,
        modalidade: Optional[str] = None
    ) -> RegrasConsolidacaoCanal:
        """
        Busca regras ou retorna defaults hardcoded.
        
        Args:
            canal_venda_id: ID do canal de venda (None = usar global)
            modalidade: Modalidade logística (None = todas)
        
        Returns:
            Regras de consolidação (nunca None)
        """
        regras = self.get_regras_canal(canal_venda_id, modalidade)
        
        if regras:
            return regras
        
        # Defaults hardcoded
        return RegrasConsolidacaoCanal(
            canal_venda_id=canal_venda_id,
            modalidade=modalidade,
            janela_agrupamento_horas=4,
            agrupar_por_produto=True,
            agrupar_por_miolo=True,
            agrupar_por_data_entrega=True,
            comportamento_pos_edicao='ADICIONAR_COM_SINALIZACAO',
            comportamento_pos_publicacao='CRIAR_NOVO_RASCUNHO'
        )
    
    def get_regra_para_pedido(
        self,
        canal_venda_id: int,
        modalidade: str
    ) -> RegrasConsolidacaoCanal:
        """
        Busca regra específica para um pedido (canal + modalidade).
        
        Args:
            canal_venda_id: ID do canal de venda
            modalidade: Modalidade logística do pedido
        
        Returns:
            Regras de consolidação (nunca None)
        """
        return self.get_regras_ou_defaults(canal_venda_id, modalidade)
    
    def deve_agrupar_pedidos(
        self,
        pedido1: Dict[str, Any],
        pedido2: Dict[str, Any],
        canal_venda_id: int,
        modalidade: Optional[str] = None
    ) -> bool:
        """
        Verifica se dois pedidos devem ser agrupados na mesma demanda.
        
        Args:
            pedido1: Dados do primeiro pedido
            pedido2: Dados do segundo pedido
            canal_venda_id: ID do canal de venda
            modalidade: Modalidade logística (opcional)
        
        Returns:
            True se devem ser agrupados
        """
        regras = self.get_regras_ou_defaults(canal_venda_id, modalidade)
        
        # Verificar janela de tempo
        try:
            data1 = self._parse_date(pedido1.get('created_at'))
            data2 = self._parse_date(pedido2.get('created_at'))
            
            if data1 and data2:
                diferenca_horas = abs((data2 - data1).total_seconds() / 3600)
                
                if diferenca_horas > regras.janela_agrupamento_horas:
                    logger.debug(
                        "Pedidos não agrupados: diferença de %.1f horas > janela de %d horas",
                        diferenca_horas,
                        regras.janela_agrupamento_horas
                    )
                    return False
        except Exception as e:
            logger.warning("Erro ao calcular diferença de tempo: %s", str(e))
        
        # Verificar produto
        if regras.agrupar_por_produto:
            if pedido1.get('produto_id') != pedido2.get('produto_id'):
                logger.debug("Pedidos não agrupados: produtos diferentes")
                return False
        
        # Verificar miolo
        if regras.agrupar_por_miolo:
            if pedido1.get('id_produto_miolo') != pedido2.get('id_produto_miolo'):
                logger.debug("Pedidos não agrupados: miolos diferentes")
                return False
        
        # Verificar data de entrega
        if regras.agrupar_por_data_entrega:
            if pedido1.get('data_entrega') != pedido2.get('data_entrega'):
                logger.debug("Pedidos não agrupados: datas de entrega diferentes")
                return False
        
        logger.debug("Pedidos podem ser agrupados")
        return True
    
    def _parse_date(self, value: Any) -> Optional[datetime]:
        """Parse date de string ISO."""
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
    
    # ========================================================================
    # CRUD
    # ========================================================================
    
    def get_regra_por_id(self, regra_id: int) -> Optional[RegrasConsolidacaoCanal]:
        """
        Busca regra por ID.
        
        Args:
            regra_id: ID da regra
        
        Returns:
            Regra ou None
        """
        response = self.table.select('*').eq('id', regra_id).execute()
        
        if not response.data:
            return None
        
        return RegrasConsolidacaoCanal.from_dict(response.data[0])
    
    def criar_regra(
        self,
        canal_venda_id: Optional[int] = None,
        modalidade: Optional[str] = None,
        agrupar_por_produto: bool = True,
        agrupar_por_miolo: bool = True,
        agrupar_por_data_entrega: bool = True,
        janela_agrupamento_horas: int = 4,
        comportamento_pos_edicao: str = 'ADICIONAR_COM_SINALIZACAO',
        comportamento_pos_publicacao: str = 'CRIAR_NOVO_RASCUNHO'
    ) -> Dict[str, Any]:
        """
        Cria nova regra de consolidação.
        
        Args:
            canal_venda_id: ID do canal de venda (None = regra global)
            modalidade: Modalidade (None = todas)
            agrupar_por_produto: Se agrupa por produto
            agrupar_por_miolo: Se agrupa por miolo
            agrupar_por_data_entrega: Se agrupa por data de entrega
            janela_agrupamento_horas: Janela de tempo para agrupamento (0 = demanda direta)
            comportamento_pos_edicao: ADICIONAR_COM_SINALIZACAO ou CRIAR_NOVO_RASCUNHO
            comportamento_pos_publicacao: CRIAR_NOVO_RASCUNHO ou SUGERIR_FUSAO
        
        Returns:
            Regra criada
        
        Raises:
            ValueError: Se validação falhar
        """
        regra = RegrasConsolidacaoCanal(
            canal_venda_id=canal_venda_id,
            modalidade=modalidade,
            agrupar_por_produto=agrupar_por_produto,
            agrupar_por_miolo=agrupar_por_miolo,
            agrupar_por_data_entrega=agrupar_por_data_entrega,
            janela_agrupamento_horas=janela_agrupamento_horas,
            comportamento_pos_edicao=comportamento_pos_edicao,
            comportamento_pos_publicacao=comportamento_pos_publicacao
        )
        
        errors = regra.validate()
        if errors:
            raise ValueError(f"Validação falhou: {'; '.join(errors)}")
        
        data = {
            'canal_venda_id': canal_venda_id,
            'modalidade': modalidade,
            'agrupar_por_produto': agrupar_por_produto,
            'agrupar_por_miolo': agrupar_por_miolo,
            'agrupar_por_data_entrega': agrupar_por_data_entrega,
            'janela_agrupamento_horas': janela_agrupamento_horas,
            'comportamento_pos_edicao': comportamento_pos_edicao,
            'comportamento_pos_publicacao': comportamento_pos_publicacao
        }
        
        response = self.table.insert(data).execute()
        
        if not response.data:
            raise Exception("Falha ao criar regra")
        
        canal_str = str(canal_venda_id) if canal_venda_id else 'GLOBAL'
        modal_str = modalidade or 'TODAS'
        
        logger.info(
            "Regra criada: canal=%s, modalidade=%s, janela=%dh",
            canal_str,
            modal_str,
            janela_agrupamento_horas
        )
        
        return response.data[0]
    
    def atualizar_regra(
        self,
        regra_id: int,
        janela_agrupamento_horas: Optional[int] = None,
        agrupar_por_produto: Optional[bool] = None,
        agrupar_por_miolo: Optional[bool] = None,
        agrupar_por_data_entrega: Optional[bool] = None,
        comportamento_demanda_existente: Optional[str] = None,
        politica_consolidacao: Optional[str] = None,
        intervalo_consideracao_minutos: Optional[int] = None,
        descricao: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Atualiza regra existente.
        
        Args:
            regra_id: ID da regra
            janela_agrupamento_horas: Nova janela (opcional)
            agrupar_por_produto: Novo flag (opcional)
            agrupar_por_miolo: Novo flag (opcional)
            agrupar_por_data_entrega: Novo flag (opcional)
            comportamento_demanda_existente: Novo comportamento (opcional)
            politica_consolidacao: Nova política (opcional)
            intervalo_consideracao_minutos: Novo intervalo (opcional)
            descricao: Nova descrição (opcional)
        
        Returns:
            Regra atualizada
        
        Raises:
            ValueError: Se regra não existir ou validação falhar
        """
        existente = self.get_regra_por_id(regra_id)
        if not existente:
            raise ValueError(f"Regra {regra_id} não encontrada")
        
        update_data = {}
        
        if janela_agrupamento_horas is not None:
            update_data['janela_agrupamento_horas'] = janela_agrupamento_horas
        if agrupar_por_produto is not None:
            update_data['agrupar_por_produto'] = agrupar_por_produto
        if agrupar_por_miolo is not None:
            update_data['agrupar_por_miolo'] = agrupar_por_miolo
        if agrupar_por_data_entrega is not None:
            update_data['agrupar_por_data_entrega'] = agrupar_por_data_entrega
        if comportamento_demanda_existente is not None:
            update_data['comportamento_demanda_existente'] = comportamento_demanda_existente
        if politica_consolidacao is not None:
            update_data['politica_consolidacao'] = politica_consolidacao
        if intervalo_consideracao_minutos is not None:
            update_data['intervalo_consideracao_minutos'] = intervalo_consideracao_minutos
        if descricao is not None:
            update_data['descricao'] = descricao
        
        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        response = self.table.update(update_data).eq('id', regra_id).execute()
        
        if not response.data:
            raise Exception("Falha ao atualizar regra")
        
        logger.info("Regra %s atualizada", regra_id)
        
        return response.data[0]
    
    def excluir_regra(self, regra_id: int) -> bool:
        """
        Exclui regra.
        
        Args:
            regra_id: ID da regra
        
        Returns:
            True se excluído com sucesso
        
        Raises:
            ValueError: Se regra não existir
        """
        existente = self.get_regra_por_id(regra_id)
        if not existente:
            raise ValueError(f"Regra {regra_id} não encontrada")
        
        self.table.delete().eq('id', regra_id).execute()
        
        logger.info("Regra %s excluída", regra_id)
        
        return True
    
    # ========================================================================
    # UTILITÁRIOS
    # ========================================================================
    
    def listar_todos_canais_com_regras(self) -> List[int]:
        """Retorna lista de IDs de canais que possuem regras configuradas."""
        response = self.table.select('canal_venda_id').execute()
        
        if not response.data:
            return []
        
        return list(set(r['canal_venda_id'] for r in response.data))


# Singleton
regras_consolidacao_service = RegrasConsolidacaoService()
