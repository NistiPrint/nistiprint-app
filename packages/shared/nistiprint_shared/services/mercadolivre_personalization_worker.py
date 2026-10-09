"""Celery tasks for Mercado Livre chat ingestion and personalization.

The tasks are registered on the application's shared Celery worker. Chat
ingestion/reconciliation and AI extraction are independent task families, and
all account-specific operations receive an integration ID explicitly.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from celery import shared_task

logger = logging.getLogger(__name__)

QUEUE = "celery"
TASK_PROCESS_INBOX = "mercadolivre.chat.process_inbox"
TASK_RECONCILE = "mercadolivre.chat.reconcile"
TASK_REPLAY_RETAINED = "mercadolivre.chat.replay_retained_events"
TASK_PROCESS_BATCH = "mercadolivre.personalization.process_batch"
TASK_RUN_DUE = "mercadolivre.personalization.run_due"
TASK_DISPATCH_DUE = "mercadolivre.personalization.dispatch_due"
TASK_RECOVER_ACCOUNT = "mercadolivre.personalization.recover_account"
TASK_DISPATCH_RECOVERY = "mercadolivre.personalization.dispatch_recovery"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redis_client():
    import redis
    return redis.Redis.from_url(
        os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
        decode_responses=True, socket_connect_timeout=2, socket_timeout=2,
    )


def _run_logged_task(task_name: str, request, origin: str, callback,
                     *, integration_id: int | None = None,
                     task_type: str = "PERSONALIZACAO_MERCADOLIVRE"):
    from nistiprint_shared.database.supabase_db_service import supabase_db

    started = _now()
    row_id = None
    try:
        fields = {
            "task_name": task_name, "task_type": task_type,
            "status": "PROCESSING", "started_at": started.isoformat(),
            "celery_task_id": getattr(request, "id", None),
            "queue_name": QUEUE, "execution_origin": origin,
            "progress_at": started.isoformat(),
            "metadata": {"marketplace": "mercadolivre", "execution_origin": origin},
        }
        if integration_id is not None:
            fields["marketplace_integration_id"] = int(integration_id)
            fields["metadata"]["integration_id"] = int(integration_id)
        inserted = supabase_db.table("task_execution_logs").insert(fields).execute().data or []
        row_id = inserted[0].get("id") if inserted else None
    except Exception:
        logger.exception("Could not record task start task=%s", task_name)

    try:
        result = callback()
    except Exception as exc:
        if row_id is not None:
            try:
                finished = _now()
                supabase_db.table("task_execution_logs").update({
                    "status": "FAILED", "finished_at": finished.isoformat(),
                    "progress_at": finished.isoformat(),
                    "duration_ms": int((finished - started).total_seconds() * 1000),
                    "error_message": str(exc)[:1000],
                }).eq("id", row_id).execute()
            except Exception:
                logger.exception("Could not record task failure task=%s", task_name)
        raise

    if row_id is not None:
        try:
            finished = _now()
            supabase_db.table("task_execution_logs").update({
                "status": "COMPLETED", "finished_at": finished.isoformat(),
                "progress_at": finished.isoformat(),
                "duration_ms": int((finished - started).total_seconds() * 1000),
                "metadata": {"marketplace": "mercadolivre",
                             "execution_origin": origin,
                             **({"integration_id": int(integration_id)} if integration_id is not None else {}),
                             "result": json.dumps(result, ensure_ascii=False, default=str)[:1000]},
            }).eq("id", row_id).execute()
        except Exception:
            logger.exception("Could not record task completion task=%s", task_name)
    return result


def _active_accounts() -> list[dict]:
    from nistiprint_shared.services.mercadolivre_personalization_service import available_integrations
    return [row for row in available_integrations()
            if row.get("is_active") and row.get("application_id_configured")
            and row.get("account_user_id")]


def _is_schedule_due(settings: dict, local_now: datetime) -> bool:
    if not settings.get("enabled", True) or not settings.get("extraction_enabled", True):
        return False
    if not settings.get("schedule_enabled", True):
        return False
    try:
        due_minute = int(settings.get("schedule_hour", 9)) * 60 + int(settings.get("schedule_minute", 0))
    except (TypeError, ValueError):
        logger.warning("Invalid Mercado Livre daily schedule: %s", settings)
        return False
    return (local_now.hour * 60 + local_now.minute >= due_minute
            and str(settings.get("last_scheduled_run_date") or "")[:10] != local_now.date().isoformat())


@shared_task(name=TASK_PROCESS_INBOX, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def process_chat_inbox(self, limit: int = 25):
    """Process durable Mercado Livre notifications; this task never invokes AI."""
    from nistiprint_shared.services.mercadolivre_personalization_service import process_inbox_once
    return _run_logged_task(
        TASK_PROCESS_INBOX, self.request, "webhook_ingest",
        lambda: process_inbox_once(limit=limit), task_type="INGESTAO_MERCADOLIVRE",
    )


@shared_task(name=TASK_RECONCILE, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def reconcile_chats(self, limit: int = 25):
    """Recover unread/history gaps per account, independently of AI extraction."""
    from nistiprint_shared.services.mercadolivre_personalization_service import (
        _reconcile_account_once,
    )

    def reconcile():
        totals = {"reconciled": 0, "unread_recovered": 0, "reconcile_errors": 0}
        for account in _active_accounts():
            integration_id = int(account["integration_id"])
            try:
                result = _reconcile_account_once(integration_id, limit=limit)
                totals["reconciled"] += result["reconciled"]
                totals["unread_recovered"] += result["unread_recovered"]
            except Exception:
                totals["reconcile_errors"] += 1
                logger.exception("Mercado Livre chat reconciliation failed integration=%s", integration_id)
        return totals

    return _run_logged_task(
        TASK_RECONCILE, self.request, "recovery", reconcile,
        task_type="INGESTAO_MERCADOLIVRE",
    )


@shared_task(name=TASK_REPLAY_RETAINED, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def replay_retained_chat_events(self, limit: int = 500):
    """Requeue old messages-topic events retained before chat routing existed."""
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.webhook_monitoring_service import webhook_monitoring_service

    def replay():
        rows = (supabase_db.table("webhook_events").select("id")
                .eq("source", "mercadolivre").eq("provider_topic", "messages")
                .eq("last_status", "skipped_unsupported_topic")
                .order("received_at").limit(min(max(int(limit), 1), 1000)).execute().data or [])
        queued = sum(bool(webhook_monitoring_service.reprocess_event(int(row["id"])).get("queued"))
                     for row in rows)
        return {"retained": len(rows), "queued": queued}

    return _run_logged_task(
        TASK_REPLAY_RETAINED, self.request, "recovery", replay,
        task_type="INGESTAO_MERCADOLIVRE",
    )


@shared_task(name=TASK_PROCESS_BATCH, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def process_personalization_batch(self, integration_id: int, batch_id: str):
    from nistiprint_shared.services.mercadolivre_personalization_service import process_batch
    from nistiprint_shared.database.supabase_db_service import supabase_db
    integration_id = int(integration_id)
    result = _run_logged_task(
        TASK_PROCESS_BATCH, self.request, "manual_or_scheduled",
        lambda: process_batch(integration_id, str(batch_id)), integration_id=integration_id,
    )
    if result.get("status") in {"completed", "failed"}:
        queued = (supabase_db.table("mercadolivre_personalization_batches").select("id")
                  .eq("marketplace_integration_id", integration_id).eq("status", "PENDING")
                  .order("created_at").limit(1).execute().data or [])
        if queued:
            process_personalization_batch.apply_async(
                args=[integration_id, str(queued[0]["id"])], queue=QUEUE,
            )
    return result


@shared_task(name=TASK_RUN_DUE, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def run_due_personalization(self, integration_id: int):
    """Queue a due account batch once per local date under a short Redis lock."""
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.mercadolivre_personalization_service import (
        _queue_packs, _settings,
    )

    integration_id = int(integration_id)
    local_now = _now().astimezone(ZoneInfo("America/Sao_Paulo"))
    run_date = local_now.date().isoformat()
    lock = _redis_client().lock(
        f"np:ml-personalization:daily-lock:{integration_id}:{run_date}",
        timeout=3600, blocking=False,
    )
    if not lock.acquire(blocking=False):
        return {"status": "already_running", "integration_id": integration_id}
    try:
        settings = _settings(integration_id)
        if not _is_schedule_due(settings, local_now):
            return {"status": "not_due_or_already_ran", "integration_id": integration_id}

        def execute():
            current = _settings(integration_id)
            now = _now().astimezone(ZoneInfo("America/Sao_Paulo"))
            if now.date().isoformat() != run_date:
                return {"status": "date_changed", "integration_id": integration_id}
            if not _is_schedule_due(current, now):
                return {"status": "not_due_or_already_ran", "integration_id": integration_id}
            queued = _queue_packs(
                integration_id, limit=int(current.get("max_processing") or 50),
            )
            supabase_db.table("mercadolivre_personalization_config").update({
                "last_scheduled_run_date": run_date,
                "updated_at": _now().isoformat(),
            }).eq("marketplace_integration_id", integration_id).execute()
            if queued.get("batch_id"):
                try:
                    process_personalization_batch.apply_async(
                        args=[integration_id, str(queued["batch_id"])], queue=QUEUE,
                    )
                except Exception:
                    # The durable batch remains PENDING and the recovery task
                    # will publish it again; don't create a duplicate daily batch.
                    logger.exception("Could not dispatch scheduled batch integration=%s batch=%s",
                                     integration_id, queued["batch_id"])
            return {"status": "queued", "integration_id": integration_id,
                    "batch_id": queued.get("batch_id"), "total": queued.get("total", 0)}

        return _run_logged_task(
            TASK_RUN_DUE, self.request, "scheduled", execute, integration_id=integration_id,
        )
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Could not release Mercado Livre schedule lock integration=%s", integration_id)


@shared_task(name=TASK_DISPATCH_DUE, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def dispatch_due_personalization(self):
    local_now = _now().astimezone(ZoneInfo("America/Sao_Paulo"))
    due = []
    for account in _active_accounts():
        if not _is_schedule_due(account, local_now):
            continue
        integration_id = int(account["integration_id"])
        run_due_personalization.apply_async(args=[integration_id], queue=QUEUE)
        due.append(integration_id)
    return {"status": "dispatched", "integration_ids": due}


@shared_task(name=TASK_RECOVER_ACCOUNT, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def recover_personalization_account(self, integration_id: int):
    from nistiprint_shared.services.mercadolivre_personalization_service import recover_batches
    integration_id = int(integration_id)
    return _run_logged_task(
        TASK_RECOVER_ACCOUNT, self.request, "recovery",
        lambda: recover_batches(integration_id), integration_id=integration_id,
    )


@shared_task(name=TASK_DISPATCH_RECOVERY, bind=True, acks_late=True,
             reject_on_worker_lost=True, autoretry_for=(Exception,),
             retry_backoff=True, retry_backoff_max=600, max_retries=3)
def dispatch_personalization_recovery(self):
    integration_ids = []
    for account in _active_accounts():
        if not account.get("enabled"):
            continue
        integration_id = int(account["integration_id"])
        recover_personalization_account.apply_async(args=[integration_id], queue=QUEUE)
        integration_ids.append(integration_id)
    return {"status": "dispatched", "integration_ids": integration_ids}


def submit_batch(integration_id: int, batch_id: str) -> None:
    """Publish manual extraction to the shared worker's default queue."""
    from nistiprint_shared.services.celery_app import celery_app
    celery_app.send_task(
        TASK_PROCESS_BATCH, args=[int(integration_id), str(batch_id)], queue=QUEUE,
    )
