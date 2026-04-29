# ===========================================
# CELERY TASKS - REDIS QUEUE CONSUMER
# ===========================================
# Task simplificada: apenas lê do Redis e registra log
# ===========================================

import json
import logging
from datetime import datetime
from celery import shared_task
import redis
from nistiprint_shared.services.bling_order_processing_service import process_webhook
from nistiprint_shared.services.correlation_service import get_correlation_id, set_correlation_id, generate_correlation_id
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
import uuid

logger = logging.getLogger(__name__)

def log_shared_task_execution(task_type: str = None):
    """
    Decorator para registrar execução de tarefas do shared package em task_execution_logs.
    Similar ao task_logger.py mas adaptado para shared_task.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extrair ou gerar correlation_id
            correlation_id = kwargs.get('correlation_id') or get_correlation_id()
            if not correlation_id:
                correlation_id = str(uuid.uuid4())
            
            # Configurar no contexto
            set_correlation_id(correlation_id)
            
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
                        'args': str(args)[:500],
                        'kwargs': str(kwargs)[:500]
                    }
                }).execute()
                
                task_log_id = log_res.data[0]['id'] if log_res.data else None
            except Exception as e:
                logger.error(f"Erro ao registrar início da tarefa {func.__name__}: {e}")
            
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


# Configuração do Redis
REDIS_HOST = 'redis'
REDIS_PORT = 6379
REDIS_DB = 0

# Filas
BLING_WEBHOOK_QUEUE = 'bling:webhooks:pendentes'
BLING_WEBHOOK_DEAD_LETTER = 'bling:webhooks:dead-letter'
BLING_WEBHOOK_FALHAS = 'bling:webhooks:falhas'
BLING_WEBHOOK_PROCESSADOS = 'bling:webhooks:processados' # Fila para log/histórico

_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    return _redis_client

def get_queue_stats():
    """Retorna o tamanho de todas as filas"""
    r = get_redis_client()
    return {
        'pendentes': r.llen(BLING_WEBHOOK_QUEUE),
        'processados': r.llen(BLING_WEBHOOK_PROCESSADOS),
        'falhas': r.llen(BLING_WEBHOOK_FALHAS),
        'dead_letter': r.llen(BLING_WEBHOOK_DEAD_LETTER)
    }

def get_queue_items(queue_name: str, limit: int = 50):
    """Retorna os itens de uma fila específica (sem remover)"""
    r = get_redis_client()
    actual_queue = {
        'pendentes': BLING_WEBHOOK_QUEUE,
        'processados': BLING_WEBHOOK_PROCESSADOS,
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(queue_name)
    
    if not actual_queue:
        return []
        
    items = r.lrange(actual_queue, 0, limit - 1)
    return [json.loads(i) if isinstance(i, str) and (i.startswith('{') or i.startswith('[')) else i for i in items]

def clear_queue(queue_name: str):
    """Limpa uma fila específica"""
    r = get_redis_client()
    actual_queue = {
        'pendentes': BLING_WEBHOOK_QUEUE,
        'processados': BLING_WEBHOOK_PROCESSADOS,
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(queue_name)
    
    if actual_queue:
        return r.delete(actual_queue)
    return 0

def move_items(source: str, destination: str = 'pendentes'):
    """Move todos os itens de uma fila para outra (ex: falhas -> pendentes)"""
    r = get_redis_client()
    src_queue = {
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(source)
    dest_queue = BLING_WEBHOOK_QUEUE if destination == 'pendentes' else None
    
    if not src_queue or not dest_queue:
        return 0
        
    count = 0
    while True:
        item = r.lpop(src_queue)
        if not item:
            break
        r.rpush(dest_queue, item)
        count += 1
    return count


@shared_task(name='nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling')
@log_shared_task_execution(task_type='INTEGRACAO')
def consumir_fila_bling(correlation_id=None):
    """
    Consome a fila de webhooks do Bling no Redis e processa cada um.
    """
    # Configurar correlation_id
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        r = get_redis_client()
        processados = 0

        # Consumir fila (máx 50 por ciclo)
        for _ in range(50):
            mensagem_str = r.lpop(BLING_WEBHOOK_QUEUE)
            if not mensagem_str:
                break

            try:
                # O payload pode vir direto ou dentro de uma chave 'body' (depende de como o n8n salva)
                data = json.loads(mensagem_str)
                
                # Log raw payload for debugging
                logger.info(f"Raw payload recebido do Redis: {mensagem_str[:500]}")
                
                # Validate payload has required fields
                if not data or not isinstance(data, dict):
                    logger.error(f"Payload inválido: não é um dicionário ou está vazio. Payload: {mensagem_str[:200]}")
                    r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)
                    continue
                
                # Extract order data - Bling webhooks nest the actual order in a 'data' field
                order_data = data.get('data') if data.get('data') and isinstance(data.get('data'), dict) else data
                
                # Extract companyId from webhook wrapper for Bling instance resolution
                company_id = data.get('companyId') if data.get('companyId') else None
                
                # Check for minimum required fields to avoid CNPJ errors
                bling_id = order_data.get('id')
                numero = order_data.get('numero')
                numero_loja = order_data.get('numeroLoja')
                
                if not bling_id and not numero and not numero_loja:
                    logger.error(f"Payload sem campos obrigatórios (id, numero, numeroLoja). Payload: {mensagem_str[:200]}")
                    r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)
                    continue
                
                logger.info(f"Iniciando processamento do webhook Bling no worker... (bling_id={bling_id}, numero={numero}, numeroLoja={numero_loja}, companyId={company_id})")
                result = process_webhook(order_data, company_id=company_id)
                
                status_result = result.get('status', 'unknown')
                msg_result = result.get('message', '')
                
                logger.info(f"Resultado do processamento: {status_result} - {msg_result}")

                if status_result == 'success' or status_result == 'skipped':
                    # Log de sucesso ou ignorado (filtros) vai para a fila de processados
                    # Adicionamos o resultado ao JSON para o monitor exibir
                    log_data = {
                        'payload': data,
                        'result': result,
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    r.rpush(BLING_WEBHOOK_PROCESSADOS, json.dumps(log_data))
                    r.ltrim(BLING_WEBHOOK_PROCESSADOS, -100, -1)
                    processados += 1
                else:
                    # Falha real no processamento (ex: erro de API ou Banco)
                    logger.error(f"Falha ao processar webhook: {msg_result}")
                    r.rpush(BLING_WEBHOOK_FALHAS, mensagem_str)

            except Exception as e:
                logger.error(f"Erro crítico ao processar mensagem do Redis: {str(e)}")
                r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)

        return {'status': 'success', 'sent': processados}

    except Exception as e:
        logger.error(f"Falha no consumer: {str(e)}")
        return {'status': 'error', 'message': str(e)}

@shared_task(name='nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens')
@log_shared_task_execution(task_type='INTEGRACAO')
def sync_firestore_tokens(correlation_id=None):
    """
    Sincroniza tokens do Bling do Firestore para o Supabase.
    """
    # Configurar correlation_id
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        from nistiprint_shared.services.token_manager.sync_firestore import sync_bling_to_supabase
        logger.info("Iniciando task agendada de sincronização com Firestore...")
        success = sync_bling_to_supabase()
        return {'status': 'success' if success else 'error'}
    except Exception as e:
        logger.error(f"Erro na task sync_firestore_tokens: {str(e)}")
        return {'status': 'error', 'message': str(e)}
