"""Dedicated Celery application factory for one Mercado Livre account.

Run one messages process, one `worker` process and one `beat` process for each
installed integration. Every broker queue and scheduled task is pinned to that
integration ID; the Shopee Celery application and schedule are not imported.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)


def _run_logged_task(integration_id: int, task_name: str, queue: str, request, origin: str, callback):
    from nistiprint_shared.database.supabase_db_service import supabase_db
    started = datetime.now(timezone.utc)
    try:
        import redis
        progress_client = redis.Redis.from_url(os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
                                              socket_connect_timeout=1, socket_timeout=1)
        progress_client.set(f"np:ml-personalization:progress:{int(integration_id)}:worker",
                            started.isoformat(), ex=86400)
    except Exception:
        progress_client = None
    row_id = None
    try:
        inserted = (supabase_db.table("task_execution_logs").insert({
            "task_name": task_name, "task_type": "PERSONALIZACAO_MERCADOLIVRE",
            "status": "PROCESSING", "started_at": started.isoformat(),
            "marketplace_integration_id": int(integration_id),
            "celery_task_id": getattr(request, "id", None), "queue_name": queue,
            "execution_origin": origin, "progress_at": started.isoformat(),
            "metadata": {"integration_id": int(integration_id), "execution_origin": origin},
        }).execute().data or [])
        row_id = inserted[0].get("id") if inserted else None
    except Exception:
        logger.exception("Could not record task start task=%s integration=%s", task_name, integration_id)
    try:
        result = callback()
    except Exception as exc:
        if progress_client:
            try: progress_client.set(f"np:ml-personalization:progress:{int(integration_id)}:worker", datetime.now(timezone.utc).isoformat(), ex=86400)
            except Exception: pass
        if row_id is not None:
            try:
                finished = datetime.now(timezone.utc)
                supabase_db.table("task_execution_logs").update({
                    "status": "FAILED", "finished_at": finished.isoformat(),
                    "progress_at": finished.isoformat(), "duration_ms": int((finished-started).total_seconds()*1000),
                    "error_message": str(exc)[:1000],
                }).eq("id", row_id).execute()
            except Exception:
                logger.exception("Could not record task failure task=%s", task_name)
        raise
    if row_id is not None:
        try:
            finished = datetime.now(timezone.utc)
            supabase_db.table("task_execution_logs").update({
                "status": "COMPLETED", "finished_at": finished.isoformat(),
                "progress_at": finished.isoformat(), "duration_ms": int((finished-started).total_seconds()*1000),
                "metadata": {"integration_id": int(integration_id), "execution_origin": origin,
                             "result": json.dumps(result, ensure_ascii=False, default=str)[:1000]},
            }).eq("id", row_id).execute()
        except Exception:
            logger.exception("Could not record task completion task=%s", task_name)
    if progress_client:
        try: progress_client.set(f"np:ml-personalization:progress:{int(integration_id)}:worker", datetime.now(timezone.utc).isoformat(), ex=86400)
        except Exception: pass
    return result


def _start_account_heartbeat(integration_id: int, role: str):
    import redis
    client = redis.Redis.from_url(os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
                                 socket_connect_timeout=2, socket_timeout=2)
    stopping = threading.Event()
    key = f"np:ml-personalization:heartbeat:{int(integration_id)}:{role}"

    def beat():
        while not stopping.is_set():
            try:
                client.set(key, datetime.now(timezone.utc).isoformat(), ex=90)
            except Exception:
                logger.exception("Could not update account heartbeat integration=%s role=%s", integration_id, role)
            stopping.wait(20)

    thread = threading.Thread(target=beat, name=f"meli-heartbeat-{integration_id}-{role}", daemon=True)
    thread.start()
    return stopping, client


def _stop_children(children: dict[int, dict[str, subprocess.Popen]]) -> None:
    for group in children.values():
        for process in group.values():
            if process.poll() is None:
                process.terminate()
    for group in children.values():
        for process in group.values():
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
    children.clear()


def run_account_supervisor() -> None:
    """Maintain one isolated messages/worker/beat trio for every active Meli account."""
    import redis
    broker = os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0")
    client = redis.Redis.from_url(broker)
    lock_key = "nistiprint:mercadolivre-personalization:account-supervisor"
    owner = f"{os.getpid()}-{time.time_ns()}"
    children: dict[int, dict[str, subprocess.Popen]] = {}
    running = True
    lock_held = False
    recovered_chat_events = False

    def stop(_signum=None, _frame=None):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        from nistiprint_shared.services.mercadolivre_personalization_service import available_integrations
        while running:
            if not lock_held:
                lock_held = bool(client.set(lock_key, owner, nx=True, ex=60))
                if not lock_held:
                    time.sleep(10)
                    continue
            if not recovered_chat_events:
                recovered_chat_events = True
                try:
                    from nistiprint_shared.database.supabase_db_service import supabase_db
                    from nistiprint_shared.services.webhook_monitoring_service import webhook_monitoring_service
                    missed = (supabase_db.table("webhook_events").select("id")
                              .eq("source", "mercadolivre")
                              .eq("provider_topic", "messages")
                              .eq("last_status", "skipped_unsupported_topic")
                              .order("received_at").limit(500).execute().data or [])
                    queued = sum(bool(webhook_monitoring_service.reprocess_event(int(row["id"])).get("queued"))
                                 for row in missed)
                    if queued:
                        logger.info("Requeued %d retained Mercado Livre chat notifications", queued)
                except Exception:
                    logger.exception("Could not recover retained Mercado Livre chat notifications")
            try:
                active_ids = {int(row["integration_id"]) for row in available_integrations()
                              if row.get("is_active") and row.get("application_id_configured")
                              and row.get("account_user_id")}
                for integration_id in set(children) - active_ids:
                    _stop_children({integration_id: children.pop(integration_id)})
                    logger.info("Stopped Mercado Livre personalization processes integration=%s", integration_id)
                for integration_id in active_ids:
                    group = children.setdefault(integration_id, {})
                    for role in ("messages", "worker", "beat"):
                        process = group.get(role)
                        if process is None or process.poll() is not None:
                            group[role] = subprocess.Popen([
                                sys.executable, "-m",
                                "nistiprint_shared.services.mercadolivre_personalization_worker",
                                role, "--integration-id", str(integration_id),
                            ], env=os.environ.copy())
                            logger.info("Started Mercado Livre %s process integration=%s pid=%s",
                                        role, integration_id, group[role].pid)
                time.sleep(20)
                renewed = client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('expire', KEYS[1], 60) else return 0 end",
                    1, lock_key, owner,
                )
                if not renewed:
                    logger.error("Lost Mercado Livre personalization supervisor lock")
                    _stop_children(children)
                    lock_held = False
            except Exception:
                logger.exception("Could not reconcile Mercado Livre account processes")
                try:
                    renewed = client.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] then "
                        "return redis.call('expire', KEYS[1], 60) else return 0 end",
                        1, lock_key, owner,
                    )
                except Exception:
                    renewed = 0
                if not renewed:
                    # Stop every account consumer if leader ownership cannot be
                    # confirmed, so another supervisor can take over safely.
                    _stop_children(children)
                    lock_held = False
                time.sleep(10)
    finally:
        _stop_children(children)
        try:
            client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                        1, lock_key, owner)
        except Exception:
            logger.warning("Could not release Mercado Livre supervisor lock")


def build_account_app(integration_id: int) -> tuple[Celery, str]:
    try:
        from nistiprint_shared.utils.env_loader import load_nistiprint_env
        from nistiprint_shared.database.initializer import setup_mock_query_interface
        load_nistiprint_env()
        setup_mock_query_interface()
    except ImportError:
        pass
    integration_id = int(integration_id)
    if integration_id <= 0:
        raise ValueError("integration_id deve ser positivo")
    from nistiprint_shared.services.mercadolivre_personalization_service import _integration
    _integration(integration_id)
    broker = os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0")
    queue = f"meli_personalization_{integration_id}"
    app = Celery(f"meli_personalization_{integration_id}", broker=broker, backend=None)
    app.conf.update(
        timezone="America/Sao_Paulo", enable_utc=True,
        task_default_queue=queue, task_default_exchange=queue,
        task_default_routing_key=queue, task_queues={
            queue: {"exchange": queue, "routing_key": queue}},
        task_serializer="json", accept_content=["json"],
        task_acks_late=True, worker_prefetch_multiplier=1,
        task_ignore_result=False, task_store_errors_even_if_ignored=False,
    )

    @app.task(name=f"mercadolivre.personalization.process_batch.{integration_id}", bind=True,
              max_retries=3)
    def process_batch_task(_self, batch_id: str):
        from nistiprint_shared.services.mercadolivre_personalization_service import process_batch
        return _run_logged_task(integration_id, _self.name, queue, _self.request, "manual",
                                lambda: process_batch(integration_id, str(batch_id)))

    @app.task(name=f"mercadolivre.personalization.process_due.{integration_id}")
    def process_due_task():
        from nistiprint_shared.services.mercadolivre_personalization_service import (
            _queue_packs, _settings, process_batch,
        )
        check = _settings(integration_id)
        now_local = datetime.now(ZoneInfo("America/Sao_Paulo"))
        due_minute = int(check.get("schedule_hour", 9)) * 60 + int(check.get("schedule_minute", 0))
        if not check.get("schedule_enabled", True):
            return {"status": "schedule_paused", "integration_id": integration_id}
        if now_local.hour * 60 + now_local.minute < due_minute:
            return {"status": "not_due", "integration_id": integration_id}
        if str(check.get("last_scheduled_run_date") or "")[:10] == now_local.date().isoformat():
            return {"status": "already_ran", "integration_id": integration_id}
        def execute():
            config = _settings(integration_id)
            if not config.get("schedule_enabled", True):
                return {"status": "schedule_paused", "integration_id": integration_id}
            local_now = datetime.now(ZoneInfo("America/Sao_Paulo"))
            scheduled_minutes = int(config.get("schedule_hour", 9)) * 60 + int(config.get("schedule_minute", 0))
            if local_now.hour * 60 + local_now.minute < scheduled_minutes:
                return {"status": "not_due", "integration_id": integration_id}
            today = local_now.date().isoformat()
            if str(config.get("last_scheduled_run_date") or "")[:10] == today:
                return {"status": "already_ran", "integration_id": integration_id}
            queued = _queue_packs(integration_id, limit=int(config.get("max_processing") or 50))
            if queued.get("batch_id"):
                process_batch(integration_id, queued["batch_id"])
            from nistiprint_shared.database.supabase_db_service import supabase_db
            supabase_db.table("mercadolivre_personalization_config").update({
                "last_scheduled_run_date": today,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("marketplace_integration_id", integration_id).execute()
            return {"status": "complete", "integration_id": integration_id,
                    "total": queued.get("total", 0)}
        return _run_logged_task(integration_id, f"mercadolivre.personalization.process_due.{integration_id}",
                                queue, process_due_task.request, "scheduled", execute)

    @app.task(name=f"mercadolivre.personalization.recover.{integration_id}")
    def recover_task():
        from nistiprint_shared.services.mercadolivre_personalization_service import recover_batches
        return _run_logged_task(integration_id, f"mercadolivre.personalization.recover.{integration_id}",
                                queue, recover_task.request, "recovery",
                                lambda: recover_batches(integration_id))

    from nistiprint_shared.services.mercadolivre_personalization_service import _settings
    config = _settings(integration_id)
    app.conf.beat_schedule = {
        f"meli-personalization-daily-{integration_id}": {
            "task": f"mercadolivre.personalization.process_due.{integration_id}",
            # Per-account settings are checked by the task itself, so saving a
            # new hour applies without restarting the Shopee or other accounts.
            "schedule": crontab(),
            "options": {"queue": queue},
        },
        f"meli-personalization-recover-{integration_id}": {
            "task": f"mercadolivre.personalization.recover.{integration_id}",
            "schedule": 300, "options": {"queue": queue},
        },
    }
    return app, queue


def submit_batch(integration_id: int, batch_id: str) -> None:
    app, queue = build_account_app(integration_id)
    app.send_task(f"mercadolivre.personalization.process_batch.{int(integration_id)}",
                  args=[str(batch_id)], queue=queue)


def run_messages(integration_id: int) -> None:
    from nistiprint_shared.services.mercadolivre_personalization_service import reconcile_once
    interval = max(30, int(os.getenv("MERCADOLIVRE_CHAT_RECONCILE_SECONDS", "120")))
    stopping, heartbeat_client = _start_account_heartbeat(integration_id, "messages")
    while True:
        delay = interval
        try:
            result = reconcile_once(integration_id)
            heartbeat_client.set(f"np:ml-personalization:progress:{integration_id}:messages",
                                 datetime.now(timezone.utc).isoformat(), ex=86400)
            if result.get("claimed") or result.get("reconciled"):
                logger.info("Mercado Livre messages integration=%s result=%s", integration_id, result)
        except Exception as exc:
            logger.exception("Mercado Livre message consumer failed integration=%s", integration_id)
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                delay = max(delay, min(3600, int(float(retry_after))))
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker isolado de personalização Mercado Livre")
    parser.add_argument("role", choices=("accounts", "messages", "worker", "beat"))
    parser.add_argument("--integration-id", type=int)
    parser.add_argument("--loglevel", default=os.getenv("WORKER_LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)
    if args.role == "accounts":
        if args.integration_id is not None:
            parser.error("accounts supervision manages every connected account; omit --integration-id")
        run_account_supervisor()
        return
    if args.integration_id is None:
        parser.error("--integration-id é obrigatório para messages, worker e beat")
    app, queue = build_account_app(args.integration_id)
    if args.role == "messages":
        run_messages(args.integration_id)
    elif args.role == "worker":
        stopping, _ = _start_account_heartbeat(args.integration_id, "worker")
        try:
            app.worker_main(["worker", "--loglevel", args.loglevel, "--concurrency", "1", "-Q", queue])
        finally:
            stopping.set()
    else:
        schedule_path = f"/tmp/celerybeat-mercadolivre-{args.integration_id}.db"
        stopping, _ = _start_account_heartbeat(args.integration_id, "beat")
        try:
            app.start(["celery", "beat", "--loglevel", args.loglevel, "--schedule", schedule_path])
        finally:
            stopping.set()


if __name__ == "__main__":
    main()
