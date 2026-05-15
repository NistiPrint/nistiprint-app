"""
Demandas Sugestões Service

Serviço unificado para calcular sugestões de valores herdados para demandas.
Usado por TODAS as fontes de geração de demanda (planilha, múltiplos pedidos, direta).

Nova arquitetura:
- Centraliza lógica de sugestões em um único serviço
- Calcula valores baseados em regras_logisticas_canal
- Retorna alertas e bloqueios para validação
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, date, time, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.logistica_coleta_service import logistica_coleta_service
import logging

logger = logging.getLogger("DemandasSugestoesService")


class DemandasSugestoesService:
    """Serviço para calcular sugestões de valores para demandas."""
    
    # Mapeamento de modalidade para prazo em dias
    PRAZO_POR_MODALIDADE = {
        'EXPRESS': 1,
        'STANDARD': 2,
        'FULFILLMENT': 3,
        'RETIRADA': 1
    }
    
    # Horário de expediente
    HORARIO_EXPEDICIO_INICIO = time(8, 0)
    HORARIO_EXPEDICIO_FIM = time(18, 0)
    
    @classmethod
    def calcular_sugestoes(
        cls,
        canal_venda_id: Optional[int] = None,
        marketplace_integration_id: Optional[int] = None,
        tipo_demanda: str = 'PLATAFORMA',
        data_entrega: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Calcula valores sugeridos baseados no canal de venda.
        
        Args:
            canal_venda_id: ID do canal de venda
            tipo_demanda: Tipo de demanda (PLATAFORMA, B2B, FULFILLMENT, ESTOQUE_INTERNO)
            data_entrega: Data de entrega prevista (para calcular data_limite_execucao)
        
        Returns:
            Dicionário com:
            {
                'horario_coleta': '14:00',
                'modalidade_logistica': 'STANDARD',
                'data_limite_execucao': '2026-04-13',
                'is_flex': False,
                'fulfillment': False,
                'prazo_dias': 2,
                'horario_limite': '15:00',
                'regra_origem': 'regras_logisticas_canal',
                'alertas': []
            }
        """
        try:
            modalidade_sugerida = 'STANDARD'
            contexto = {}
            if marketplace_integration_id:
                contexto = logistica_coleta_service.calcular_contexto_coleta(
                    marketplace_integration_id=marketplace_integration_id,
                    modalidade=modalidade_sugerida,
                )
            elif canal_venda_id:
                contexto = logistica_coleta_service.resolver_por_canal(
                    canal_venda_id=canal_venda_id,
                    modalidade=modalidade_sugerida,
                )

            if not contexto.get('tem_regra'):
                return cls._get_valores_padrao()

            prazo_dias = cls.PRAZO_POR_MODALIDADE.get(modalidade_sugerida, 2)
            data_limite_execucao = None
            if data_entrega:
                data_limite_execucao = data_entrega - timedelta(days=prazo_dias)

            return {
                'horario_coleta': contexto.get('proxima_coleta_horario'),
                'modalidade_logistica': modalidade_sugerida,
                'data_limite_execucao': cls._format_date(data_limite_execucao),
                'is_flex': modalidade_sugerida == 'EXPRESS',
                'fulfillment': modalidade_sugerida == 'FULFILLMENT',
                'prazo_dias': prazo_dias,
                'horario_limite': contexto.get('deadline_final_horario'),
                'regra_origem': 'regras_logisticas_integracao',
                'alertas': [],
                'coleta_contexto': contexto,
            }
                
        except Exception as e:
            logger.error(f"Erro ao calcular sugestões: {e}", exc_info=True)
            return cls._get_valores_padrao()
    
    @classmethod
    def validar_override(
        cls,
        campo: str,
        valor_alterado: Any,
        canal_venda_id: Optional[int] = None,
        marketplace_integration_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Valida se um override é compatível com as regras do canal.
        
        Args:
            campo: Campo a validar (horario_coleta, modalidade_logistica, etc.)
            valor_alterado: Valor que o usuário quer alterar
            canal_venda_id: ID do canal de venda
        
        Returns:
            {
                'valid': True,
                'alertas': ['Horário após limite de coleta'],
                'bloqueios': []
            }
        """
        try:
            if not marketplace_integration_id and canal_venda_id:
                cc = (
                    supabase_db.table('channel_connections')
                    .select('marketplace_integration_id')
                    .eq('channel_id', canal_venda_id)
                    .eq('is_active', True)
                    .not_.is_('marketplace_integration_id', 'null')
                    .limit(1)
                    .execute()
                )
                if cc.data:
                    marketplace_integration_id = cc.data[0].get('marketplace_integration_id')

            if campo == 'horario_coleta':
                try:
                    hh = int(str(valor_alterado).split(':')[0])
                    mm = int(str(valor_alterado).split(':')[1])
                except Exception:
                    return {'valid': False, 'alertas': [], 'bloqueios': ['Formato de horário inválido']}
                if hh < 8 or hh > 18 or (hh == 18 and mm > 0):
                    return {'valid': False, 'alertas': [], 'bloqueios': ['Horário fora do expediente (08:00-18:00)']}

                contexto = logistica_coleta_service.calcular_contexto_coleta(
                    marketplace_integration_id=marketplace_integration_id,
                    modalidade='STANDARD',
                )
                alertas = []
                if contexto.get('deadline_final_horario') and str(valor_alterado) > contexto['deadline_final_horario']:
                    alertas.append(f"Horário após limite da integração ({contexto['deadline_final_horario']})")
                return {'valid': True, 'alertas': alertas, 'bloqueios': []}

            return {'valid': True, 'alertas': [], 'bloqueios': []}
                
        except Exception as e:
            logger.error(f"Erro ao validar override: {e}", exc_info=True)
            return {'valid': True, 'alertas': [], 'bloqueios': []}  # Fail open
    
    @classmethod
    def _get_valores_padrao(cls) -> Dict[str, Any]:
        """Retorna valores padrão quando não há regras definidas."""
        return {
            'horario_coleta': '14:00',
            'modalidade_logistica': 'STANDARD',
            'data_limite_execucao': None,
            'is_flex': False,
            'fulfillment': False,
            'prazo_dias': 2,
            'horario_limite': '14:00',
            'regra_origem': 'padrao_sistema',
            'alertas': ['Canal sem regras logísticas definidas']
        }
    
    @classmethod
    def _format_time(cls, value) -> Optional[str]:
        """Formata time para string HH:MM."""
        if value is None:
            return None
        if isinstance(value, str):
            return value[:5]  # HH:MM
        if isinstance(value, time):
            return value.strftime('%H:%M')
        return str(value)
    
    @classmethod
    def _format_date(cls, value) -> Optional[str]:
        """Formata date para string YYYY-MM-DD."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        return str(value)
    
    @classmethod
    def get_justificativas_tipo(cls) -> List[Dict[str, str]]:
        """
        Retorna lista de justificativas pré-definidas para overrides.
        
        Returns:
            [
                {'value': 'COLETA_ALTERNATIVA', 'label': 'Coleta Alternativa'},
                ...
            ]
        """
        return [
            {
                'value': 'COLETA_ALTERNATIVA',
                'label': 'Coleta Alternativa',
                'description': 'Plataforma definiu horário alternativo no dia'
            },
            {
                'value': 'MUDANCA_CLIENTE',
                'label': 'Mudança Solicitada pelo Cliente',
                'description': 'Cliente pediu alteração de prazo/horário'
            },
            {
                'value': 'ERRO_OPERACIONAL',
                'label': 'Correção de Erro Operacional',
                'description': 'Correção de erro de lançamento ou processo'
            },
            {
                'value': 'OTIMIZACAO_LOGISTICA',
                'label': 'Otimização Logística',
                'description': 'Melhoria operacional ou de logística'
            },
            {
                'value': 'OUTRO',
                'label': 'Outro',
                'description': 'Outro motivo não listado'
            }
        ]
