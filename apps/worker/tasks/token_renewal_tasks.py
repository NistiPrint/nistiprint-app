from celery_config import celery_app
from nistiprint_shared.services.token_renewal_service import token_renewal_service
import logging
import sys
import os

# Adicionar diretorio do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

logger = logging.getLogger(__name__)


@celery_app.task(name='tasks.token_renewal_tasks.renew_shopee_tokens')
@log_task_execution(task_type='TOKEN_RENEWAL')
def renew_shopee_tokens_task():
    """
    Tarefa Celery para renovar automaticamente tokens de integracoes Shopee.

    Esta tarefa:
    1. Busca todas as integracoes Shopee ativas
    2. Executa a mesma renovacao usada manualmente na UI
    """
    try:
        logger.info("Iniciando renovacao agendada de tokens Shopee.")
        return token_renewal_service.renew_shopee_tokens_expiring_soon()
    except Exception as e:
        logger.error(f"Erro na tarefa de renovacao de tokens Shopee: {str(e)}")
        return {'status': 'FAILED', 'error': str(e)}

@celery_app.task(name='tasks.token_renewal_tasks.renew_mercadolivre_tokens')
@log_task_execution(task_type='TOKEN_RENEWAL')
def renew_mercadolivre_tokens_task():
    """
    Tarefa Celery para renovar automaticamente tokens de integracoes Mercado Livre.
    """
    try:
        logger.info("Iniciando renovacao agendada de tokens Mercado Livre.")
        return token_renewal_service.renew_mercadolivre_tokens_expiring_soon()
    except Exception as e:
        logger.error(f"Erro na tarefa de renovacao de tokens Mercado Livre: {str(e)}")
        return {'status': 'FAILED', 'error': str(e)}
