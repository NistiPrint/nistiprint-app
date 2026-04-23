"""
Demandas Override Service

Serviço para gerenciar personalizações (overrides) de campos herdados nas demandas.
Permite registrar, listar e auditar alterações feitas pelos usuários.

Nova arquitetura:
- Centraliza gestão de overrides em um único serviço
- Registra contexto de origem (PLANILHA, PEDIDOS, DIRETA, CONSOLIDADA)
- Mantém histórico completo de alterações
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from nistiprint_shared.database.supabase_db_service import supabase_db
import logging

logger = logging.getLogger("DemandasOverrideService")


class DemandasOverrideService:
    """Serviço para gerenciar overrides de campos herdados."""
    
    # Campos que podem ter override
    CAMPOS_PERMITIDOS = [
        'horario_coleta',
        'modalidade_logistica',
        'data_limite_execucao',
        'is_flex',
        'fulfillment'
    ]
    
    # Tipos de justificativa permitidos
    JUSTIFICATIVAS_TIPO = [
        'COLETA_ALTERNATIVA',
        'MUDANCA_CLIENTE',
        'ERRO_OPERACIONAL',
        'OTIMIZACAO_LOGISTICA',
        'OUTRO'
    ]
    
    # Contextos de origem permitidos
    CONTEXTOS_ORIGEM = [
        'PLANILHA',
        'MULTIPLOS_PEDIDOS',
        'DIRETA',
        'CONSOLIDADA'
    ]
    
    @classmethod
    def registrar(
        cls,
        demanda_id: int,
        campo: str,
        valor_original: Any,
        valor_alterado: Any,
        justificativa: Optional[str] = None,
        justificativa_tipo: Optional[str] = None,
        usuario_id: Optional[int] = None,
        contexto_origem: str = 'DIRETA'
    ) -> Optional[Dict[str, Any]]:
        """
        Registra um novo override de campo.
        
        Args:
            demanda_id: ID da demanda
            campo: Campo sendo alterado (horario_coleta, modalidade_logistica, etc.)
            valor_original: Valor herdado original
            valor_alterado: Novo valor personalizado
            justificativa: Motivo da alteração (texto livre)
            justificativa_tipo: Tipo de justificativa (dropdown)
            usuario_id: ID do usuário que fez a alteração
            contexto_origem: Fonte de geração da demanda
        
        Returns:
            Override registrado ou None se erro
        """
        try:
            # Validações
            if campo not in cls.CAMPOS_PERMITIDOS:
                logger.error(f"Campo '{campo}' não permitido para override")
                return None
            
            if justificativa_tipo and justificativa_tipo not in cls.JUSTIFICATIVAS_TIPO:
                logger.error(f"Tipo de justificativa '{justificativa_tipo}' não permitido")
                return None
            
            if contexto_origem not in cls.CONTEXTOS_ORIGEM:
                logger.error(f"Contexto de origem '{contexto_origem}' não permitido")
                return None
            
            # Preparar dados
            override_data = {
                'demanda_id': demanda_id,
                'campo': campo,
                'valor_original': cls._to_jsonb(valor_original),
                'valor_alterado': cls._to_jsonb(valor_alterado),
                'justificativa': justificativa,
                'justificativa_tipo': justificativa_tipo,
                'usuario_id': usuario_id,
                'contexto_origem': contexto_origem
            }
            
            # Insert no banco
            result = supabase_db.table('demandas_overrides').insert(override_data).execute()
            
            if result.data:
                logger.info(f"Override registrado: {campo} na demanda {demanda_id}")
                return result.data[0]
            else:
                logger.error(f"Falha ao registrar override: {override_data}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao registrar override: {e}", exc_info=True)
            return None
    
    @classmethod
    def get_overrides(cls, demanda_id: int) -> List[Dict[str, Any]]:
        """
        Busca todos os overrides de uma demanda.
        
        Args:
            demanda_id: ID da demanda
        
        Returns:
            Lista de overrides com dados do usuário
        """
        try:
            result = supabase_db.table('demandas_overrides').select("""
                *,
                usuario:usuarios(nome)
            """).eq('demanda_id', demanda_id).order('created_at', desc=True).execute()
            
            if result.data:
                return result.data
            else:
                return []
                
        except Exception as e:
            logger.error(f"Erro ao buscar overrides: {e}", exc_info=True)
            return []
    
    @classmethod
    def get_override_by_campo(
        cls,
        demanda_id: int,
        campo: str
    ) -> Optional[Dict[str, Any]]:
        """
        Busca override específico por campo.
        
        Args:
            demanda_id: ID da demanda
            campo: Campo a buscar
        
        Returns:
            Override ou None
        """
        try:
            result = supabase_db.table('demandas_overrides').select("""
                *,
                usuario:usuarios(nome)
            """).eq('demanda_id', demanda_id).eq('campo', campo).order('created_at', desc=True).limit(1).execute()
            
            if result.data:
                return result.data[0]
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao buscar override por campo: {e}", exc_info=True)
            return None
    
    @classmethod
    def atualizar(
        cls,
        override_id: int,
        valor_alterado: Any,
        justificativa: Optional[str] = None,
        justificativa_tipo: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Atualiza um override existente.
        
        Args:
            override_id: ID do override
            valor_alterado: Novo valor alterado
            justificativa: Nova justificativa
            justificativa_tipo: Novo tipo de justificativa
        
        Returns:
            Override atualizado ou None
        """
        try:
            update_data = {
                'valor_alterado': cls._to_jsonb(valor_alterado),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            if justificativa:
                update_data['justificativa'] = justificativa
            
            if justificativa_tipo:
                update_data['justificativa_tipo'] = justificativa_tipo
            
            result = supabase_db.table('demandas_overrides').update(update_data).eq('id', override_id).execute()
            
            if result.data:
                logger.info(f"Override {override_id} atualizado")
                return result.data[0]
            else:
                logger.error(f"Falha ao atualizar override {override_id}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao atualizar override: {e}", exc_info=True)
            return None
    
    @classmethod
    def remover(cls, override_id: int, usuario_id: Optional[int] = None) -> bool:
        """
        Remove um override.
        
        Args:
            override_id: ID do override
            usuario_id: ID do usuário (para auditoria)
        
        Returns:
            True se removido, False se erro
        """
        try:
            # Log de auditoria antes de remover
            override = cls.get_override_by_id(override_id)
            if override:
                logger.info(f"Override {override_id} removido por usuário {usuario_id}")
            
            result = supabase_db.table('demandas_overrides').delete().eq('id', override_id).execute()
            return result.data is not None
            
        except Exception as e:
            logger.error(f"Erro ao remover override: {e}", exc_info=True)
            return False
    
    @classmethod
    def get_override_by_id(cls, override_id: int) -> Optional[Dict[str, Any]]:
        """Busca override por ID."""
        try:
            result = supabase_db.table('demandas_overrides').select("""
                *,
                usuario:usuarios(nome)
            """).eq('id', override_id).single().execute()
            
            if result.data:
                return result.data
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao buscar override por ID: {e}", exc_info=True)
            return None
    
    @classmethod
    def _to_jsonb(cls, value: Any) -> str:
        """Converte valor para formato JSONB string."""
        if value is None:
            return 'null'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return f'"{value}"'
        # Para objetos complexos, converter para string
        return f'"{str(value)}"'
    
    @classmethod
    def registrar_lote(
        cls,
        demanda_id: int,
        overrides: List[Dict[str, Any]],
        usuario_id: Optional[int] = None,
        contexto_origem: str = 'DIRETA'
    ) -> List[Dict[str, Any]]:
        """
        Registra múltiplos overrides de uma vez.
        
        Args:
            demanda_id: ID da demanda
            overrides: Lista de dicionários com:
                - campo
                - valor_original
                - valor_alterado
                - justificativa (opcional)
                - justificativa_tipo (opcional)
            usuario_id: ID do usuário
            contexto_origem: Contexto de origem
        
        Returns:
            Lista de overrides registrados
        """
        resultados = []
        
        for override in overrides:
            resultado = cls.registrar(
                demanda_id=demanda_id,
                campo=override['campo'],
                valor_original=override['valor_original'],
                valor_alterado=override['valor_alterado'],
                justificativa=override.get('justificativa'),
                justificativa_tipo=override.get('justificativa_tipo'),
                usuario_id=usuario_id,
                contexto_origem=contexto_origem
            )
            
            if resultado:
                resultados.append(resultado)
        
        return resultados
