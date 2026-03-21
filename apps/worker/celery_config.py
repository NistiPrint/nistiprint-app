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
        'tasks.stock_tasks',
        'tasks.consolidation_tasks',
    ]
)

# Configurações otimizadas
celery_app.conf.update(
    # ... (manter configurações existentes)
    # Agendamento de tarefas periódicas
    beat_schedule={
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

# Importa explicitamente as tasks para registro
try:
    from tasks import consolidation_tasks  # noqa: F401
except ImportError:
    pass

# Auto-discovery de tasks em módulos de serviço
celery_app.autodiscover_tasks(lambda: [
    'nistiprint_shared.services.redis_queue_tasks',
    'tasks.stock_tasks',
    'tasks.consolidation_tasks',
])


@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'
