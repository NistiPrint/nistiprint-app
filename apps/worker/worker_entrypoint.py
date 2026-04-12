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
        'tasks.eventos_tasks',  # Processamento de estoque (Event Sourcing)
        'tasks.pedidos_fetch_tasks',  # Fetch Em Andamento (rede de segurança)
        'tasks.consolidation_tasks',  # Tarefas de consolidação
        'tasks.auto_consolidation_tasks',  # Auto-consolidação de pedidos
        'nistiprint_shared.services.personalizados_tasks',  # Processamento de personalização IA (shared)
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
        # Processar eventos de produção (Event Sourcing) - ÚNICO processador de estoque
        'processar-eventos-producao-periodic': {
            'task': 'tasks.eventos_tasks.process_eventos_producao',
            'schedule': 10, # A cada 10 segundos
        },
        # Nota: NÃO há processamento de lote de rascunhos — cada pedido é
        # classificado e consolidado imediatamente no momento do webhook.
        # Nota: Sincronização Shopee NÃO é periódica - ocorre no webhook do Bling (FASE 2)
        # Quando um pedido Shopee entra em "Em Andamento" (15), o webhook já busca dados da API Shopee
        #
        # IMPORTANTE: NÃO há agendamento de processamento IA aqui.
        # O processamento de IA (personalizados) é executado EXCLUSIVAMENTE sob demanda
        # via botão na UI (VendasPersonalizadasPage ou FerramentasPage).
        # Ver: apps/api/routes/personalizados.py -> processar_personalizados()
    },
)

# Task de debug
@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'


# Auto-discovery de tasks
celery_app.autodiscover_tasks([
    'tasks.eventos_tasks',
    'tasks.consolidation_tasks',
    'tasks.auto_consolidation_tasks',
    'tasks.pedidos_fetch_tasks',
    'nistiprint_shared.services.personalizados_tasks',
])
