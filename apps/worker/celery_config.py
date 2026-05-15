# ===========================================
# CELERY APP CONFIGURATION
# ===========================================
# Configuração centralizada do Celery
# ===========================================

import os
import logging
from celery import Celery

# Configuração de Logs Silenciosos para bibliotecas barulhentas
for _noisy_logger in ("httpx", "httpcore", "hpack", "urllib3", "postgrest", "supabase"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Inicialização da Infraestrutura ---
try:
    from nistiprint_shared.utils.env_loader import load_nistiprint_env
    from nistiprint_shared.database.initializer import setup_mock_query_interface
    
    # Garante que variáveis de ambiente estejam carregadas
    load_nistiprint_env()
    # Garante que a interface de banco (Supabase/Mock) esteja pronta
    setup_mock_query_interface()
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()

# Configuração do broker Redis
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

def get_default_schedules():
    """Fallback de agendamentos caso o banco esteja inacessível ou vazio."""
    return {
        'sync-firestore-tokens': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens',
            'schedule': 1800,
        },
        'consumir-fila-bling': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,
        },
        'drain-bling-webhook-failures': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.drain_bling_webhook_failures',
            'schedule': 300,
        },
        'processar-eventos-producao-periodic': {
            'task': 'tasks.eventos_tasks.process_eventos_producao',
            'schedule': 10,
        },
        'renew-shopee-tokens': {
            'task': 'tasks.token_renewal_tasks.renew_shopee_tokens',
            'schedule': 7200,
        },
    }

def load_dynamic_schedules():
    """Carrega agendamentos do banco de dados (tabela configuracoes_aplicacao)."""
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        
        config = app_config_service.get_config('celery_task_schedules')
        if not config:
            logger.warning("Configuração 'celery_task_schedules' não encontrada no banco. Usando padrões.")
            return get_default_schedules()
            
        task_schedules_config = config.get('task_schedules', {})
        schedules = {}
        
        for task_name, task_config in task_schedules_config.items():
            if task_config.get('enabled', True):
                schedules[task_name] = {
                    'task': task_config.get('task_name', task_name),
                    'schedule': task_config.get('schedule_seconds', 60),
                }
                # Log minimalista para não poluir
                logger.info(f"Task periódica ativa: {task_name} ({task_config.get('schedule_seconds')}s)")
            else:
                logger.info(f"Task periódica desativada via banco: {task_name}")
                
        return schedules
    except Exception as e:
        logger.error(f"Erro ao carregar tasks dinâmicas: {e}. Usando padrões de código.")
        return get_default_schedules()

# Criação do App Celery
celery_app = Celery(
    'nistiprint',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        'nistiprint_shared.services.redis_queue_tasks',
        'tasks.eventos_tasks',
        'tasks.consolidation_tasks',
        'tasks.pedidos_fetch_tasks',
        'tasks.token_renewal_tasks',
        'nistiprint_shared.services.bling_status_sync_service',
        'nistiprint_shared.services.ai_personalization_service',
        'tasks.stock_tasks',
    ]
)

# Roteamento e Filas
celery_app.conf.task_queues = {
    'default': {'exchange': 'default', 'routing_key': 'default'},
    'ai_personalization': {'exchange': 'ai', 'routing_key': 'ai.personalization'},
    'bling_status_sync':  {'exchange': 'bling', 'routing_key': 'bling.status'},
}

celery_app.conf.task_routes = {
    'services.ai_personalization.processar_batch': {'queue': 'ai_personalization'},
    'services.ai_personalization.processar_pedido': {'queue': 'ai_personalization'},
    'services.bling_status_sync.sync_batch': {'queue': 'bling_status_sync'},
}

# Configurações Gerais Otimizadas
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Sao_Paulo',
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule=load_dynamic_schedules()
)

@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    logger.info(f'Request: {self.request!r}')
    return 'Celery worker is running!'
