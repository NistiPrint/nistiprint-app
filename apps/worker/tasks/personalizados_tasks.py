"""
Tasks Celery para processamento de pedidos personalizados com IA.
"""

import logging
from nistiprint_shared.services.celery_app import celery_app

logger = logging.getLogger("PersonalizadosTasks")


@celery_app.task(bind=True, max_retries=3, soft_time_limit=600)
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
