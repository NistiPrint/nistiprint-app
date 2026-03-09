# ===========================================
# CELERY TASKS - REDIS QUEUE CONSUMER
# ===========================================
# Task simplificada: apenas lê do Redis e registra log
# ===========================================

import json
import logging
from celery import shared_task
import redis

logger = logging.getLogger(__name__)

# Configuração do Redis
REDIS_HOST = 'redis'
REDIS_PORT = 6379
REDIS_DB = 0

# Filas
BLING_WEBHOOK_QUEUE = 'bling:webhooks:pendentes'
BLING_WEBHOOK_DEAD_LETTER = 'bling:webhooks:dead-letter'
BLING_WEBHOOK_FALHAS = 'bling:webhooks:falhas'
BLING_WEBHOOK_PROCESSADOS = 'bling:webhooks:processados' # Nova fila para log de sucesso

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


@shared_task(name='services.redis_queue_tasks.consumir_fila_bling')
def consumir_fila_bling():
    """
    Task simplificada: Lê do Redis e registra log de processamento.
    """
    try:
        r = get_redis_client()
        processados = 0

        # Consumir fila (máx 50 por ciclo)
        for _ in range(50):
            mensagem_str = r.lpop(BLING_WEBHOOK_QUEUE)
            if not mensagem_str:
                break

            # Log simplificado
            logger.info(f"Processando mensagem {mensagem_str} da fila")

            try:
                data = json.loads(mensagem_str)

                # Normalização mínima
                webhook_data = {
                    'id': data.get('id') or data.get('payload', {}).get('id') or data.get('eventId'),
                    'event': data.get('event') or data.get('payload', {}).get('event') or data.get('event'),
                    'data': data.get('data') or data.get('payload', {}) or data
                }

                if not webhook_data['id']:
                    logger.warning(f"Mensagem inválida (sem ID): {mensagem_str}")
                    r.rpush(BLING_WEBHOOK_FALHAS, mensagem_str)
                    continue

                # SIMULAÇÃO: Apenas registra que foi processado com sucesso
                logger.info(f"Evento {webhook_data['event']} (ID: {webhook_data['id']}) processado com sucesso.")
                
                # Move para a fila de processados (mantém histórico para o monitor)
                # Limitamos o tamanho desta fila para não crescer infinitamente
                r.rpush(BLING_WEBHOOK_PROCESSADOS, mensagem_str)
                r.ltrim(BLING_WEBHOOK_PROCESSADOS, -100, -1) # Mantém apenas os últimos 100
                
                processados += 1

            except Exception as e:
                logger.error(f"Erro ao processar mensagem: {str(e)}")
                r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)

        return {'status': 'success', 'sent': processados}

    except Exception as e:
        logger.error(f"Falha no consumer: {str(e)}")
        return {'status': 'error', 'message': str(e)}

