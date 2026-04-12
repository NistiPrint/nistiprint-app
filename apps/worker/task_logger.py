# ===========================================
# TASK LOGGER DECORATOR
# ===========================================
# Decorator para registrar automaticamente execução de tarefas em task_execution_logs
# com suporte a correlation_id e rastreamento de entidades
# ===========================================

from functools import wraps
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
from nistiprint_shared.services.correlation_service import get_correlation_id, set_correlation_id, generate_correlation_id
import uuid
import logging

logger = logging.getLogger(__name__)


def log_task_execution(task_type: str = None):
    """
    Decorator para registrar automaticamente execução de tarefas em task_execution_logs
    com suporte a correlation_id e rastreamento de entidades.
    
    Args:
        task_type: Tipo/categoria da tarefa (ex: 'PEDIDO', 'ESTOQUE', 'INTEGRACAO')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extrair ou gerar correlation_id
            correlation_id = kwargs.get('correlation_id') or get_correlation_id()
            if not correlation_id:
                correlation_id = str(uuid.uuid4())
            
            # Configurar no contexto
            set_correlation_id(correlation_id)
            
            # Extrair entity_type e entity_id se disponíveis
            entity_type = kwargs.get('entity_type')
            entity_id = kwargs.get('entity_id')
            
            # Registrar início
            task_log_id = None
            try:
                log_res = supabase_db.table('task_execution_logs').insert({
                    'task_name': func.__name__,
                    'task_type': task_type,
                    'status': 'PROCESSING',
                    'correlation_id': correlation_id,
                    'started_at': get_now_iso(),
                    'metadata': {
                        'args': str(args)[:500],  # Limitar tamanho
                        'kwargs': str(kwargs)[:500],
                        'entity_type': entity_type,
                        'entity_id': entity_id
                    }
                }).execute()
                
                task_log_id = log_res.data[0]['id'] if log_res.data else None
            except Exception as e:
                logger.error(f"Erro ao registrar início da tarefa {func.__name__}: {e}")
            
            # Mapear entity -> correlation_id
            if entity_type and entity_id:
                try:
                    supabase_db.table('entity_correlation_mapping').insert({
                        'entity_type': entity_type,
                        'entity_id': entity_id,
                        'correlation_id': correlation_id
                    }).execute()
                except Exception as e:
                    logger.error(f"Erro ao mapear entity {entity_type}:{entity_id} -> correlation_id: {e}")
            
            try:
                # Executar tarefa
                result = func(*args, **kwargs)
                
                # Registrar sucesso
                if task_log_id:
                    try:
                        supabase_db.table('task_execution_logs').update({
                            'status': 'COMPLETED',
                            'finished_at': get_now_iso(),
                            'metadata': {'result': str(result)[:500]}
                        }).eq('id', task_log_id).execute()
                    except Exception as e:
                        logger.error(f"Erro ao registrar sucesso da tarefa {func.__name__}: {e}")
                
                return result
                
            except Exception as e:
                # Registrar falha
                logger.error(f"Erro na execução da tarefa {func.__name__}: {e}")
                if task_log_id:
                    try:
                        supabase_db.table('task_execution_logs').update({
                            'status': 'FAILED',
                            'finished_at': get_now_iso(),
                            'error_message': str(e)[:1000]
                        }).eq('id', task_log_id).execute()
                    except Exception as log_error:
                        logger.error(f"Erro ao registrar falha da tarefa {func.__name__}: {log_error}")
                raise
                
        return wrapper
    return decorator
