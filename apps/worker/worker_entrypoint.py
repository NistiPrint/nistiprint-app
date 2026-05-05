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

# Configurar logging formatter explícito para o worker
LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# Forçar nível INFO nos loggers do pipeline
for name in ("bling_order_processing", "flex_classifier",
             "shopee_driver", "demanda_producao"):
    logging.getLogger(name).setLevel(logging.INFO)

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

def load_task_schedules():
    """
    Carrega configurações de tarefas periódicas do banco de dados.
    
    Retorna dicionário com configurações para beat_schedule.
    Se não houver configuração no banco, retorna configuração padrão.
    """
    try:
        from nistiprint_shared.services.app_config_service import app_config_service
        
        config = app_config_service.get_config('celery_task_schedules')
        
        if not config:
            print("⚠️ Nenhuma configuração de tarefas encontrada no banco, usando padrão")
            return get_default_schedules()
        
        task_schedules_config = config.get('task_schedules', {})
        schedules = {}
        
        for task_name, task_config in task_schedules_config.items():
            if task_config.get('enabled', True):
                schedules[task_name] = {
                    'task': task_config.get('task_name', task_name),
                    'schedule': task_config.get('schedule_seconds', 60)
                }
                print(f"✓ Tarefa '{task_name}' habilitada (freq: {task_config.get('schedule_seconds')}s)")
            else:
                print(f"○ Tarefa '{task_name}' desabilitada")
        
        if not schedules:
            print("⚠️ Nenhuma tarefa habilitada, beat_schedule vazio")
        
        return schedules
        
    except Exception as e:
        print(f"⚠️ Erro ao carregar configurações do banco: {e}")
        print("Usando configurações padrão")
        return get_default_schedules()

def get_default_schedules():
    """
    Retorna configurações padrão de tarefas periódicas.
    Usado como fallback quando não há configuração no banco.
    """
    return {
        'sync-firestore-tokens': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens',
            'schedule': 1800,  # 30 minutos
        },
        'consumir-fila-bling': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling',
            'schedule': 30,  # 30 segundos
        },
        'drain-bling-webhook-failures': {
            'task': 'nistiprint_shared.services.redis_queue_tasks.drain_bling_webhook_failures',
            'schedule': 300,  # 5 minutos
        },
        'processar-eventos-producao-periodic': {
            'task': 'tasks.eventos_tasks.process_eventos_producao',
            'schedule': 10,  # 10 segundos
        },
        'renew-shopee-tokens': {
            'task': 'tasks.token_renewal_tasks.renew_shopee_tokens',
            'schedule': 7200,  # 6 horas
        },
    }

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
    # Carrega configurações dinâmicas do banco de dados
    beat_schedule=load_task_schedules(),
)

# Task de debug
@celery_app.task(bind=True)
def debug_task(self):
    """Task de debug para testar conexão Celery"""
    print(f'Request: {self.request!r}')
    return 'Celery worker is running!'


# Tasks já incluídas explicitamente no parâmetro 'include' acima
# autodiscover_tasks removido para evitar ModuleNotFoundError
