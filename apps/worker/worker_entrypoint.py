"""
Worker entrypoint for Celery.

This module configures the worker logger to write both to stdout/stderr
for journald and to a daily rotated file for later inspection.
"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger

LOG_FORMAT = "%(levelname)s %(name)s %(message)s"
DEFAULT_LOG_LEVEL = os.environ.get("WORKER_LOG_LEVEL", "INFO").upper()
DEFAULT_LOG_FILE = os.environ.get("WORKER_LOG_FILE", "/var/log/nistiprint/worker.log")
DEFAULT_LOG_BACKUP_COUNT = int(os.environ.get("WORKER_LOG_BACKUP_COUNT", "30"))
PIPELINE_LOGGERS = (
    "bling_order_processing",
    "flex_classifier",
    "shopee_driver",
    "demanda_producao",
)
ROLE_ARGS = {arg.lower() for arg in sys.argv[1:]}
IS_WORKER_PROCESS = "worker" in ROLE_ARGS
_SHARED_HANDLERS = []


def _get_log_level():
    return getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO)


def _has_handler(logger_obj, handler_type, *, base_filename=None, stream=None):
    for handler in logger_obj.handlers:
        if not isinstance(handler, handler_type):
            continue
        if base_filename is not None and getattr(handler, "baseFilename", None) != base_filename:
            continue
        if stream is not None and getattr(handler, "stream", None) is not stream:
            continue
        return True
    return False


def _ensure_log_directory(log_path):
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)


def _create_stream_handler():
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(_get_log_level())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _create_file_handler():
    _ensure_log_directory(DEFAULT_LOG_FILE)
    handler = TimedRotatingFileHandler(
        DEFAULT_LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=DEFAULT_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    handler.setLevel(_get_log_level())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _build_shared_handlers():
    handlers = [_create_stream_handler()]

    if IS_WORKER_PROCESS:
        try:
            handlers.append(_create_file_handler())
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to initialize worker file logging at %s; continuing with stdout only",
                DEFAULT_LOG_FILE,
            )

    return handlers


def _configure_logger(logger_obj):
    logger_obj.setLevel(_get_log_level())

    for handler in _SHARED_HANDLERS:
        handler_type = type(handler)
        if isinstance(handler, TimedRotatingFileHandler):
            if _has_handler(logger_obj, handler_type, base_filename=handler.baseFilename):
                continue
        elif isinstance(handler, logging.StreamHandler):
            if _has_handler(logger_obj, handler_type, stream=handler.stream):
                continue
        logger_obj.addHandler(handler)


def configure_worker_logging():
    global _SHARED_HANDLERS

    _SHARED_HANDLERS = _build_shared_handlers()

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.propagate = False
    _configure_logger(root_logger)

    for logger_name in PIPELINE_LOGGERS:
        logger_obj = logging.getLogger(logger_name)
        logger_obj.propagate = True
        logger_obj.setLevel(_get_log_level())


@after_setup_logger.connect
def _configure_celery_logger(logger=None, *args, **kwargs):
    if logger is not None:
        _configure_logger(logger)


@after_setup_task_logger.connect
def _configure_celery_task_logger(logger=None, *args, **kwargs):
    if logger is not None:
        _configure_logger(logger)


configure_worker_logging()
logger = logging.getLogger(__name__)

try:
    from nistiprint_shared.database.initializer import setup_mock_query_interface
    from nistiprint_shared.utils.env_loader import load_nistiprint_env

    load_nistiprint_env()
    setup_mock_query_interface()
    logger.info("Worker infrastructure initialized from shared package")
except ImportError as exc:
    logger.warning(
        "Shared package bootstrap unavailable; falling back to local dotenv loading: %s",
        exc,
    )
    from dotenv import load_dotenv

    load_dotenv()


CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")


def load_task_schedules():
    """
    Load periodic task settings from the database.

    Returns a dictionary for beat_schedule.
    Falls back to defaults when there is no database configuration.
    """
    try:
        from nistiprint_shared.services.app_config_service import app_config_service

        config = app_config_service.get_config("celery_task_schedules")

        if not config:
            logger.warning("No task schedule configuration found in database; using defaults")
            return get_default_schedules()

        task_schedules_config = config.get("task_schedules", {})
        schedules = {}

        for task_name, task_config in task_schedules_config.items():
            if task_config.get("enabled", True):
                schedules[task_name] = {
                    "task": task_config.get("task_name", task_name),
                    "schedule": task_config.get("schedule_seconds", 60),
                }
                logger.info(
                    "Enabled periodic task '%s' with interval %ss",
                    task_name,
                    task_config.get("schedule_seconds"),
                )
            else:
                logger.info("Disabled periodic task '%s'", task_name)

        if not schedules:
            logger.warning("No periodic tasks enabled; beat_schedule is empty")

        return schedules

    except Exception:
        logger.exception("Failed to load task schedules from database; using defaults")
        return get_default_schedules()


def get_default_schedules():
    """Return default periodic task settings."""
    return {
        "sync-firestore-tokens": {
            "task": "nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens",
            "schedule": 1800,
        },
        "consumir-fila-bling": {
            "task": "nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling",
            "schedule": 30,
        },
        "drain-bling-webhook-failures": {
            "task": "nistiprint_shared.services.redis_queue_tasks.drain_bling_webhook_failures",
            "schedule": 300,
        },
        "processar-eventos-producao-periodic": {
            "task": "tasks.eventos_tasks.process_eventos_producao",
            "schedule": 10,
        },
        "renew-shopee-tokens": {
            "task": "tasks.token_renewal_tasks.renew_shopee_tokens",
            "schedule": 7200,
        },
    }


celery_app = Celery(
    "nistiprint_worker",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "nistiprint_shared.services.redis_queue_tasks",
        "tasks.eventos_tasks",
        "tasks.pedidos_fetch_tasks",
        "tasks.consolidation_tasks",
        "tasks.auto_consolidation_tasks",
        "tasks.token_renewal_tasks",
        "nistiprint_shared.services.personalizados_tasks",
    ],
)

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
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=IS_WORKER_PROCESS,
    worker_redirect_stdouts_level=DEFAULT_LOG_LEVEL,
    result_expires=3600,
    beat_schedule=load_task_schedules(),
)


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task used to verify Celery connectivity."""
    logger.info("Debug task request: %r", self.request)
    return "Celery worker is running!"
