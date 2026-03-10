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
from nistiprint_shared.services.bling_order_processing_service import bling_order_processing_service

logger = logging.getLogger(__name__)

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
def consumir_fila_bling():
    """
    Consome a fila de webhooks do Bling no Redis e processa cada um.
    """
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
                
                logger.info(f"Iniciando processamento do webhook Bling no worker...")
                result = bling_order_processing_service.process_webhook(data)
                
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
def sync_firestore_tokens():
    """
    Sincroniza tokens do Bling do Firestore para o Supabase.
    """
    try:
        from nistiprint_shared.services.token_manager.sync_firestore import sync_bling_to_supabase
        logger.info("Iniciando task agendada de sincronização com Firestore...")
        success = sync_bling_to_supabase()
        return {'status': 'success' if success else 'error'}
    except Exception as e:
        logger.error(f"Erro na task sync_firestore_tokens: {str(e)}")
        return {'status': 'error', 'message': str(e)}
