"""Dedicated Celery application factory for one Mercado Livre account.

Run one messages process, one `worker` process and one `beat` process for each
installed integration. Every broker queue and scheduled task is pinned to that
integration ID; the Shopee Celery application and schedule are not imported.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)


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
        return process_batch(integration_id, str(batch_id))

    @app.task(name=f"mercadolivre.personalization.process_due.{integration_id}")
    def process_due_task():
        from nistiprint_shared.services.mercadolivre_personalization_service import (
            _queue_packs, _settings, process_batch,
        )
        config = _settings(integration_id)
        if not config.get("enabled") or not config.get("extraction_enabled"):
            return {"status": "disabled", "integration_id": integration_id}
        if not config.get("capture_enabled"):
            return {"status": "capture_disabled", "integration_id": integration_id}
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

    @app.task(name=f"mercadolivre.personalization.recover.{integration_id}")
    def recover_task():
        from nistiprint_shared.services.mercadolivre_personalization_service import recover_batches
        return recover_batches(integration_id)

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
    while True:
        delay = interval
        try:
            result = reconcile_once(integration_id)
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
        app.worker_main(["worker", "--loglevel", args.loglevel, "--concurrency", "1", "-Q", queue])
    else:
        schedule_path = f"/tmp/celerybeat-mercadolivre-{args.integration_id}.db"
        app.start(["celery", "beat", "--loglevel", args.loglevel, "--schedule", schedule_path])


if __name__ == "__main__":
    main()
