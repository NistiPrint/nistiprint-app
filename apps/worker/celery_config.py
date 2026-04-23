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
        'nistiprint_shared.services.webhook_tasks',
        'nistiprint_shared.services.redis_queue_tasks',
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
        # Processamento de webhooks pendentes a cada 5 minutos
        'process-pending-webhooks': {
            'task': 'nistiprint_shared.services.webhook_tasks.process_pending_webhooks',
            'schedule': crontab(minute='*/5'),
        },
        # Consumir fila do Bling no Redis (contínuo)
        'consumir-fila-bling': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,  # A cada 30 segundos (esvazia até 50 por vez)
        },
        # Processar fila de estoque a cada 10 segundos (High Frequency Outbox)
        'processar-fila-estoque-periodic': {
            'task': 'tasks.stock_tasks.process_stock_queue',
            'schedule': 10, # A cada 10 segundos
        },
    },
)

@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'
