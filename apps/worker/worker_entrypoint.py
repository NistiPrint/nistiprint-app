"""
Worker entrypoint for Celery.

This module configures the worker logger to write both to stdout/stderr
for journald and to a daily rotated file for later inspection.
It also provides the unified 'celery_app' instance for the worker.
"""

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

# Importa o app centralizado do celery_config
from celery_config import celery_app
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


# Aplica configurações de log específicas do worker
configure_worker_logging()

# Atualiza configurações do app (herdados do celery_config) com parâmetros de execução
celery_app.conf.update(
    task_track_started=True,
    task_send_sent_event=True,
    task_soft_time_limit=300,
    task_time_limit=600,
    worker_max_tasks_per_child=1000,
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=IS_WORKER_PROCESS,
    worker_redirect_stdouts_level=DEFAULT_LOG_LEVEL,
    result_expires=3600,
)
