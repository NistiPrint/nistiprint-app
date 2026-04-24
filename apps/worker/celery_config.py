# ===========================================
# CELERY APP CONFIGURATION
# ===========================================
# Configuração centralizada do Celery para o backend Flask
# ===========================================

import os
from celery import Celery
from celery.schedules import crontab

# Configuração do broker Redis
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

# Configurações da aplicação Celery
celery_app = Celery(
    'nistiprint',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        'nistiprint_shared.services.redis_queue_tasks',
        'tasks.eventos_tasks',
        'tasks.consolidation_tasks',
        'tasks.pedidos_fetch_tasks',
        'tasks.personalizados_tasks',
        'tasks.token_renewal_tasks',
        'nistiprint_shared.services.bling_status_sync_service',
        'nistiprint_shared.services.ai_personalization_service',
        'tasks.stock_tasks',
    ]
)

# Part C 3.7: Configuração de filas e roteamento
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

# Configurações otimizadas
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Agendamento de tarefas periódicas
    beat_schedule={
        # Sincronização de tokens Bling do Firestore para Supabase (a cada 30 min)
        'sync-firestore-tokens': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens',
            'schedule': 1800,  # 30 minutos (em segundos)
        },
        # Consumir fila do Bling no Redis (contínuo)
        'consumir-fila-bling': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,  # A cada 30 segundos
        },
        # NOVO: Processar eventos de produção (Event Sourcing) a cada 10 segundos
        'processar-eventos-producao-periodic': {
            'task': 'tasks.eventos_tasks.process_eventos_producao',
            'schedule': 10, # A cada 10 segundos
        },
        # NOVO: Renovação automática de tokens Shopee (a cada 6 horas)
        'renew-shopee-tokens': {
            'task': 'tasks.token_renewal_tasks.renew_shopee_tokens',
            'schedule': 7200,  # 6 horas (em segundos)
        },

    },
)

# Importa explicitamente as tasks para registro
try:
    from tasks import eventos_tasks, consolidation_tasks  # noqa: F401
except ImportError:
    pass

# Auto-discovery de tasks em módulos de serviço
celery_app.autodiscover_tasks(lambda: [
    'nistiprint_shared.services.redis_queue_tasks',
    'tasks.eventos_tasks',
    'tasks.consolidation_tasks',
    'tasks.pedidos_fetch_tasks',
    'tasks.personalizados_tasks',
    'tasks.token_renewal_tasks',
])


@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'
