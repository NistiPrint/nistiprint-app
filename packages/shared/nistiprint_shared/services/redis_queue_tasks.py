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
                    'id': data.get('id') or data.get('payload', {}).get('id'),
                    'event': data.get('event') or data.get('payload', {}).get('event'),
                    'data': data.get('data') or data.get('payload', {})
                }

                if not webhook_data['id']:
                    logger.warning(f"Mensagem inválida (sem ID): {mensagem_str}")
                    r.rpush(BLING_WEBHOOK_FALHAS, mensagem_str)
                    continue

                processados += 1

            except Exception as e:
                logger.error(f"Erro ao processar mensagem: {str(e)}")
                r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)

        return {'status': 'success', 'sent': processados}

    except Exception as e:
        logger.error(f"Falha no consumer: {str(e)}")
        return {'status': 'error', 'message': str(e)}

