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
        # Nota: tasks do worker são registradas via worker_entrypoint.py
        # Este arquivo é usado apenas pelo Flask app (backend) para enviar tasks
    ]
)

# Configurações otimizadas
celery_app.conf.update(
    # Serialização
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Sao_Paulo',
    enable_utc=True,
    
    # Confiabilidade
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_send_sent_event=True,
    
    # Timeouts
    task_soft_time_limit=300,
    task_time_limit=600,
    
    # Retry automático para falhas temporárias
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_max_retries=3,
    
    # Rate limiting (pode ser ajustado por tarefa)
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    
    # Resultado expira após 1 hora
    result_expires=3600,
    
    # Agendamento de tarefas periódicas
    beat_schedule={
        # Processamento de webhooks pendentes a cada 5 minutos
        'process-pending-webhooks': {
            'task': 'services.webhook_tasks.process_pending_webhooks',
            'schedule': crontab(minute='*/5'),
        },
        # Consumir fila do Bling no Redis (contínuo)
        'consumir-fila-bling': {
            'task': 'services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,  # A cada 30 segundos (esvazia até 50 por vez)
        },
        # Drenar falhas do Bling de volta para pendentes
        'drain-bling-webhook-failures': {
            'task': 'services.redis_queue_tasks.drain_bling_webhook_failures',
            'schedule': 300,  # A cada 5 minutos
        },
    },
)

# Auto-discovery de tasks em módulos de serviço
# Nota: tasks reais são registradas no worker_entrypoint.py
celery_app.autodiscover_tasks(lambda: [])


@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'

