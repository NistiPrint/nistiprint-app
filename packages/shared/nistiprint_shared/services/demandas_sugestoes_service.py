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
        canal_venda_id: int,
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
            # Chamar função SQL fn_sugerir_valores_demanda
            result = supabase_db.rpc(
                'fn_sugerir_valores_demanda',
                {
                    'p_canal_venda_id': canal_venda_id,
                    'p_tipo_demanda': tipo_demanda,
                    'p_data_entrega': data_entrega.isoformat() if data_entrega else None
                }
            ).execute()
            
            if result.data:
                row = result.data[0] if isinstance(result.data, list) else result.data
                
                # Converter para formato amigável
                sugestoes = {
                    'horario_coleta': cls._format_time(row.get('horario_coleta_sugerido')),
                    'modalidade_logistica': row.get('modalidade_logistica_sugerida', 'STANDARD'),
                    'data_limite_execucao': cls._format_date(row.get('data_limite_execucao_sugerida')),
                    'is_flex': row.get('is_flex_sugerido', False),
                    'fulfillment': row.get('fulfillment_sugerido', False),
                    'prazo_dias': row.get('prazo_dias', 2),
                    'horario_limite': cls._format_time(row.get('horario_limite')),
                    'regra_origem': row.get('regra_origem', 'padrao_sistema'),
                    'alertas': row.get('alertas', [])
                }
                
                logger.debug(f"Sugestões calculadas para canal {canal_venda_id}: {sugestoes}")
                return sugestoes
            else:
                # Fallback: valores padrão
                logger.warning(f"Função fn_sugerir_valores_demanda não retornou dados para canal {canal_venda_id}")
                return cls._get_valores_padrao()
                
        except Exception as e:
            logger.error(f"Erro ao calcular sugestões: {e}", exc_info=True)
            return cls._get_valores_padrao()
    
    @classmethod
    def validar_override(
        cls,
        campo: str,
        valor_alterado: Any,
        canal_venda_id: int
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
            # Converter valor para JSONB
            if isinstance(valor_alterado, (date, datetime)):
                valor_json = valor_alterado.isoformat()
            elif isinstance(valor_alterado, time):
                valor_json = valor_alterado.strftime('%H:%M')
            elif isinstance(valor_alterado, bool):
                valor_json = str(valor_alterado).lower()
            else:
                valor_json = str(valor_alterado)
            
            # Chamar função SQL fn_validar_override_demanda
            result = supabase_db.rpc(
                'fn_validar_override_demanda',
                {
                    'p_campo': campo,
                    'p_valor_alterado': valor_json,
                    'p_canal_venda_id': canal_venda_id
                }
            ).execute()
            
            if result.data:
                row = result.data[0] if isinstance(result.data, list) else result.data
                
                validacao = {
                    'valid': row.get('valid', False),
                    'alertas': row.get('alertas', []),
                    'bloqueios': row.get('bloqueios', [])
                }
                
                logger.debug(f"Validação para {campo}: {validacao}")
                return validacao
            else:
                # Fallback: válido sem alertas
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
