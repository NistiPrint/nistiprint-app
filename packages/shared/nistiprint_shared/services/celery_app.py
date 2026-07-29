"""Celery client used by the API to publish non-webhook background tasks."""
from __future__ import annotations

import os

from celery import Celery


CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL", "redis://redis-celery:6379/0"
)

celery_app = Celery("nistiprint", broker=CELERY_BROKER_URL, include=[])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Sao_Paulo",
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
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    result_expires=int(os.environ.get("CELERY_RESULT_EXPIRES", "300")),
    # Webhooks are consumed by the blocking reliable-ingest services.
    beat_schedule={},
)
celery_app.autodiscover_tasks(lambda: [])


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
    return "Celery worker is running!"
