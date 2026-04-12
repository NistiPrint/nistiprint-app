"""
Celery Task para processamento de pedidos personalizados com IA.

Este módulo é compartilhado entre API e Worker:
- API: importa para enviar task.delay() ao broker Redis
- Worker: registra a task via celery_app.autodiscover_tasks

O worker_entrypoint.py inclui este módulo no include[] para registro.
"""

import logging
import os

logger = logging.getLogger("PersonalizadosTasks")

# Celery app para envio de tasks (API) e execução (Worker)
# Ambos usam o mesmo broker/backend via env vars
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

from celery import Celery

celery_app = Celery(
    'personalizados',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)


@celery_app.task(bind=True, name='personalizados.processar_personalizacoes',
                 max_retries=3, soft_time_limit=600)
def processar_personalizacoes_task(self, order_sn=None, limit=None):
    """
    Task Celery para processar pedidos personalizados com IA.

    Args:
        order_sn: str (processar apenas 1 pedido específico)
        limit: int (limitar quantidade de pedidos)

    Returns:
        dict com resultado do processamento
    """
    try:
        from nistiprint_shared.services.ai_personalization_service import (
            process_orders,
            get_orders_with_chats,
        )

        # Contar pedidos antes de processar
        orders = get_orders_with_chats(order_sn=order_sn, limit=limit)
        total = len(orders)

        # Atualizar meta da task para tracking de progresso
        self.update_state(state='PROCESSING', meta={
            'total': total,
            'current': 0,
            'message': f'Encontrados {total} pedidos para processar'
        })

        if total == 0:
            return {
                'success': True,
                'message': 'Nenhum pedido para processar',
                'processed': 0
            }

        # Processar pedidos
        success, message = process_orders(order_sn=order_sn, limit=limit)

        return {
            'success': success,
            'message': message,
            'total_processed': total
        }

    except Exception as e:
        logger.error(f"Erro na task processar_personalizacoes: {e}", exc_info=True)
        # Retry com backoff exponencial
        self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
