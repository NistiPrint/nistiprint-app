# ===========================================
# WORKER ENTRYPOINT (MONOREPO)
# ===========================================
# Ponto de entrada para o Celery Worker
# Uso: celery -A worker_entrypoint worker --loglevel=info
# ===========================================

import os
import logging
from celery import Celery
from celery.schedules import crontab

# 1. Inicialização do ambiente e infraestrutura compartilhada
try:
    from nistiprint_shared.utils.env_loader import load_nistiprint_env
    from nistiprint_shared.database.initializer import setup_mock_query_interface
    
    load_nistiprint_env()
    setup_mock_query_interface()
    print("✓ Worker Infrastructure Initialized (Shared Package)")
except ImportError as e:
    print(f"⚠️ Aviso: nistiprint-shared não localizado, usando ambiente local: {e}")
    from dotenv import load_dotenv
    load_dotenv()

# Configuração do broker Redis
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

# Criar aplicação Celery
celery_app = Celery(
    'nistiprint_worker',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        'nistiprint_shared.services.redis_queue_tasks',
        'tasks.stock_tasks', # Adicionando módulo de tarefas de estoque
    ]
)

# Configurações Consolidadas
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Sao_Paulo',
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_send_sent_event=True,
    task_soft_time_limit=300,
    task_time_limit=600,
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_max_retries=3,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,
    
    # Agendamento de tarefas periódicas (Beat)
    beat_schedule={
        # Sincronização de tokens Bling do Firestore para Supabase (a cada 4h)
        'sync-firestore-tokens': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens',
            'schedule': 14400,  # 4 horas (em segundos)
        },
        # Consumir fila do Bling no Redis (contínuo)
        'consumir-fila-bling': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,  # A cada 30 segundos
        },
        # Processar fila de estoque a cada 10 segundos
        'processar-fila-estoque-periodic': {
            'task': 'tasks.stock_tasks.process_stock_queue',
            'schedule': 10, # A cada 10 segundos
        },
    },
)

# Task de debug
@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'
