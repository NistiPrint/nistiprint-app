import os
from celery_config import celery_app
from nistiprint_shared.services.demanda_producao_service import demanda_producao_service

@celery_app.task(name='tasks.stock_tasks.process_stock_queue', bind=True, max_retries=3, default_retry_delay=60)
def process_stock_queue(self, limit=50):
    """
    Tarefa Celery para processar a fila de processamento de estoque.
    """
    try:
        processed_count = demanda_producao_service.processar_fila_estoque(limit=limit)
        if processed_count > 0:
            print(f"[*] Stock Worker: {processed_count} tarefas processadas com sucesso.")
        return {'status': 'SUCCESS', 'processed_count': processed_count}
    except Exception as e:
        print(f"[*] Stock Worker Error: {e}")
        self.retry(exc=e)
        return {'status': 'FAILED', 'error': str(e)}
