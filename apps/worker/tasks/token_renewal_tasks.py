from celery_config import celery_app
from nistiprint_shared.services.token_renewal_service import token_renewal_service
import logging
import sys
import os

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

logger = logging.getLogger(__name__)


@celery_app.task(name='tasks.token_renewal_tasks.renew_shopee_tokens')
@log_task_execution(task_type='TOKEN_RENEWAL')
def renew_shopee_tokens_task():
    """
    Tarefa Celery para renovar automaticamente tokens de integrações Shopee.

    Esta tarefa:
    1. Busca todas as integrações Shopee ativas
    2. Verifica se o token expira em menos de 1 hora
    3. Executa a mesma renovação usada manualmente na UI
    """
    try:
        logger.info("Iniciando renovação agendada de tokens Shopee.")
        return token_renewal_service.renew_shopee_tokens_expiring_soon()
    except Exception as e:
        logger.error(f"Erro na tarefa de renovação de tokens Shopee: {str(e)}")
        return {'status': 'FAILED', 'error': str(e)}
