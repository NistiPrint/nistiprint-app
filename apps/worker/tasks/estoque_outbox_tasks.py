"""Celery delivery task for confirmed stock operation events."""

from celery_config import celery_app
from nistiprint_shared.services.estoque_outbox_service import estoque_outbox_service


@celery_app.task(name='tasks.estoque_outbox_tasks.process_estoque_outbox')
def process_estoque_outbox(limit=50):
    return estoque_outbox_service.process_batch(limit=limit)
