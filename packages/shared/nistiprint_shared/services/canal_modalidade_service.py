"""
Canal Modalidade Service - Serviço para mapeamento de modalidade logística.

Este serviço gerencia o mapeamento configurável de padrões de servico_logistico
para modalidades logísticas internas (STANDARD, EXPRESS, FULFILLMENT, RETIRADA).

Funcionalidades:
    - Derivar modalidade a partir de servico_logistico
    - CRUD de mapeamentos por canal
    - Validação de mapeamentos
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import logging
import re

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.canal_modalidade_mapeamento import CanalModalidadeMapeamento


logger = logging.getLogger(__name__)


class CanalModalidadeService:
    """
    Serviço para gestão de mapeamentos de modalidade logística.
    """
    
    def __init__(self):
        self.table = supabase_db.table('canal_modalidade_mapeamento')
    
    # ========================================================================
    # MÉTODOS DE DERIVAÇÃO (CORE)
    # ========================================================================
    
    def derivar_modalidade(
        self,
        canal_venda_id: int,
        servico_logistico: str
    ) -> Optional[str]:
        """
        Deriva modalidade logística a partir do servico_logístico.
        
        Args:
            canal_venda_id: ID do canal de venda
            servico_logistico: String do serviço logístico (ex: "Entrega Rápida Shopee")
        
        Returns:
            Modalidade (STANDARD, EXPRESS, FULFILLMENT, RETIRADA) ou None se não casar
        
        Exemplo:
            >>> service.derivar_modalidade(1, "Entrega Rápida Shopee")
            'EXPRESS'
        """
        if not servico_logistico:
            logger.warning("servico_logistico vazio para canal %s", canal_venda_id)
            return None
        
        # Tentar via função SQL (mais performático)
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
                "RPC derivar_modalidade_logistica falhou para canal %s: %s. Fallback para Python.",
                canal_venda_id,
                str(e)
            )
        
        # Fallback: implementação Python
        return self._derivar_modalidade_python(canal_venda_id, servico_logistico)
    
    def _derivar_modalidade_python(
        self,
        canal_venda_id: int,
        servico_logistico: str
    ) -> Optional[str]:
        """
        Implementação Python de derivação de modalidade (fallback).
        
        Busca mapeamentos do canal e verifica matching com padrões.
        """
        # Buscar todos os mapeamentos do canal, ordenados por prioridade
        try:
            response = self.table.select('*')\
                .eq('canal_venda_id', canal_venda_id)\
                .order('prioridade', desc=True)\
                .order('created_at', desc=True)\
                .execute()
            
            if not response.data:
                logger.debug("Nenhum mapeamento encontrado para canal %s", canal_venda_id)
                return None
            
            servico_upper = servico_logistico.upper()
            
            for mapeamento_data in response.data:
                mapeamento = CanalModalidadeMapeamento.from_dict(mapeamento_data)
                
                if mapeamento.matches_servico(servico_logistico):
                    logger.debug(
                        "Modalidade derivada para canal %s: %s (padrão: %s)",
                        canal_venda_id,
                        mapeamento.modalidade,
                        mapeamento.padroes_servico
                    )
                    return mapeamento.modalidade
            
            logger.debug(
                "Nenhum padrão casou para servico '%s' no canal %s",
                servico_logistico,
                canal_venda_id
            )
            return None
            
        except Exception as e:
            logger.error("Erro ao derivar modalidade: %s", str(e))
            return None
    
    def derivar_modalidade_com_fallback(
        self,
        canal_venda_id: int,
        servico_logistico: str,
        is_flex: bool = False,
        fulfillment: bool = False
    ) -> str:
        """
        Deriva modalidade com fallback para flags is_flex/fulfillment.
        
        Args:
            canal_venda_id: ID do canal de venda
            servico_logistico: String do serviço logístico
            is_flex: Flag de flex (fallback)
            fulfillment: Flag de fulfillment (fallback)
        
        Returns:
            Modalidade (nunca None - usa fallback)
        """
        # Tentar derivar via mapeamento
        modalidade = self.derivar_modalidade(canal_venda_id, servico_logistico)
        
        if modalidade:
            return modalidade
        
        # Fallback para flags
        if is_flex:
            logger.info(
                "Fallback para EXPRESS via is_flex (canal %s, servico: %s)",
                canal_venda_id,
                servico_logistico
            )
            return 'EXPRESS'
        
        if fulfillment:
            logger.info(
                "Fallback para FULFILLMENT via fulfillment flag (canal %s)",
                canal_venda_id
            )
            return 'FULFILLMENT'
        
        # Default final
        logger.warning(
            "Sem mapeamento para servico '%s' no canal %s. Usando STANDARD como default.",
            servico_logistico,
            canal_venda_id
        )
        return 'STANDARD'
    
    # ========================================================================
    # CRUD
    # ========================================================================
    
    def get_mapeamentos_por_canal(self, canal_venda_id: int) -> List[CanalModalidadeMapeamento]:
        """
        Busca todos os mapeamentos de um canal.
        
        Args:
            canal_venda_id: ID do canal de venda
        
        Returns:
            Lista de mapeamentos ordenados por prioridade
        """
        try:
            # Tentar via função SQL
            result = supabase_db.rpc(
                'get_mapeamentos_modalidade_canal',
                {'p_canal_venda_id': canal_venda_id}
            ).execute()
            
            if result.data and isinstance(result.data, list):
                return [CanalModalidadeMapeamento.from_dict(m) for m in result.data]
        except Exception as e:
            logger.warning(
                "RPC get_mapeamentos_modalidade_canal falhou: %s. Fallback para Python.",
                str(e)
            )
        
        # Fallback: busca direta
        response = self.table.select('*')\
            .eq('canal_venda_id', canal_venda_id)\
            .order('prioridade', desc=True)\
            .order('created_at', desc=True)\
            .execute()
        
        if not response.data:
            return []
        
        return [CanalModalidadeMapeamento.from_dict(m) for m in response.data]
    
    def get_mapeamento_por_id(self, mapeamento_id: int) -> Optional[CanalModalidadeMapeamento]:
        """
        Busca mapeamento por ID.
        
        Args:
            mapeamento_id: ID do mapeamento
        
        Returns:
            Mapeamento ou None
        """
        response = self.table.select('*')\
            .eq('id', mapeamento_id)\
            .execute()
        
        if not response.data:
            return None
        
        return CanalModalidadeMapeamento.from_dict(response.data[0])
    
    def criar_mapeamento(
        self,
        canal_venda_id: int,
        padrao_servico: str,
        modalidade: str,
        prioridade: int = 0
    ) -> Dict[str, Any]:
        """
        Cria novo mapeamento.
        
        Args:
            canal_venda_id: ID do canal de venda
            padrao_servico: Padrão LIKE (ex: '%flex%')
            modalidade: Modalidade (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)
            prioridade: Prioridade do padrão
        
        Returns:
            Mapeamento criado
        
        Raises:
            ValueError: Se validação falhar
        """
        mapeamento = CanalModalidadeMapeamento(
            canal_venda_id=canal_venda_id,
            padrao_servico=padrao_servico,
            modalidade=modalidade,
            prioridade=prioridade
        )
        
        errors = mapeamento.validate()
        if errors:
            raise ValueError(f"Validação falhou: {'; '.join(errors)}")
        
        data = {
            'canal_venda_id': canal_venda_id,
            'padrao_servico': padrao_servico,
            'modalidade': modalidade,
            'prioridade': prioridade
        }
        
        response = self.table.insert(data).execute()
        
        if not response.data:
            raise Exception("Falha ao criar mapeamento")
        
        logger.info(
            "Mapeamento criado: canal=%s, modalidade=%s, padrao=%s",
            canal_venda_id,
            modalidade,
            padrao_servico
        )
        
        return response.data[0]
    
    def atualizar_mapeamento(
        self,
        mapeamento_id: int,
        padrao_servico: Optional[str] = None,
        modalidade: Optional[str] = None,
        prioridade: Optional[int] = None,
        ativo: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Atualiza mapeamento existente.
        
        Args:
            mapeamento_id: ID do mapeamento
            padrao_servico: Novo padrão (opcional)
            modalidade: Nova modalidade (opcional)
            prioridade: Nova prioridade (opcional)
            ativo: Novo status (opcional)
        
        Returns:
            Mapeamento atualizado
        
        Raises:
            ValueError: Se mapeamento não existir ou validação falhar
        """
        existente = self.get_mapeamento_por_id(mapeamento_id)
        if not existente:
            raise ValueError(f"Mapeamento {mapeamento_id} não encontrado")
        
        update_data = {}
        
        if padrao_servico is not None:
            update_data['padrao_servico'] = padrao_servico
        if modalidade is not None:
            update_data['modalidade'] = modalidade
        if prioridade is not None:
            update_data['prioridade'] = prioridade
        if ativo is not None:
            update_data['ativo'] = ativo
        
        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        response = self.table.update(update_data).eq('id', mapeamento_id).execute()
        
        if not response.data:
            raise Exception("Falha ao atualizar mapeamento")
        
        logger.info("Mapeamento %s atualizado", mapeamento_id)
        
        return response.data[0]
    
    def excluir_mapeamento(self, mapeamento_id: int) -> bool:
        """
        Exclui mapeamento.
        
        Args:
            mapeamento_id: ID do mapeamento
        
        Returns:
            True se excluído com sucesso
        
        Raises:
            ValueError: Se mapeamento não existir
        """
        existente = self.get_mapeamento_por_id(mapeamento_id)
        if not existente:
            raise ValueError(f"Mapeamento {mapeamento_id} não encontrado")
        
        self.table.delete().eq('id', mapeamento_id).execute()
        
        logger.info("Mapeamento %s excluído", mapeamento_id)
        
        return True
    
    # ========================================================================
    # UTILITÁRIOS
    # ========================================================================
    
    def listar_todas_modalidades(self) -> List[str]:
        """Retorna lista de modalidades válidas."""
        return CanalModalidadeMapeamento.MODALIDADES_VALIDAS
    
    def sugerir_padroes_para_modalidade(
        self,
        modalidade: str,
        plataforma_nome: Optional[str] = None
    ) -> List[str]:
        """
        Sugere padrões comuns para uma modalidade.
        
        Args:
            modalidade: Modalidade desejada
            plataforma_nome: Nome da plataforma (opcional, para personalizar)
        
        Returns:
            Lista de padrões sugeridos
        """
        sugestoes = {
            'EXPRESS': [
                '%flex%',
                '%rápida%',
                '%rapida%',
                '%express%',
                '%entrega rápida%',
                '%entrega rapida%',
                'Entrega Rápida',
                'Entrega Flex'
            ],
            'STANDARD': [
                '%normal%',
                '%padrão%',
                '%padrao%',
                '%standard%',
                '%clássico%',
                '%classico%',
                'Entrega Padrão',
                'Entrega Normal'
            ],
            'FULFILLMENT': [
                '%full%',
                '%fulfillment%',
                '%reposição%',
                '%reposicao%',
                'Fulfillment'
            ],
            'RETIRADA': [
                '%retirada%',
                '%pickup%',
                'Retirada Local',
                'Retirada na Loja'
            ]
        }
        
        return sugestoes.get(modalidade, [])


# Singleton
canal_modalidade_service = CanalModalidadeService()
