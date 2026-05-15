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
    try:
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
    except Exception as e:
        print(f"Erro ao criar handler de arquivo: {e}")
        return None

def configure_worker_logging():
    global _SHARED_HANDLERS
    
    stream_h = _create_stream_handler()
    _SHARED_HANDLERS = [stream_h]
    
    file_h = _create_file_handler()
    if file_h:
        _SHARED_HANDLERS.append(file_h)

    # Configura o logger raiz
    root_logger = logging.getLogger()
    root_logger.setLevel(_get_log_level())
    for h in _SHARED_HANDLERS:
        root_logger.addHandler(h)

@after_setup_logger.connect
def _configure_celery_logger(logger=None, *args, **kwargs):
    if logger is not None:
        for h in _SHARED_HANDLERS:
            if h not in logger.handlers:
                logger.addHandler(h)

@after_setup_task_logger.connect
def _configure_celery_task_logger(logger=None, *args, **kwargs):
    if logger is not None:
        for h in _SHARED_HANDLERS:
            if h not in logger.handlers:
                logger.addHandler(h)

# Inicializa logs
configure_worker_logging()

# Configurações de execução do app
celery_app.conf.update(
    worker_hijack_root_logger=True, # Deixa o Celery propagar logs para o root que configuramos
    task_track_started=True,
    task_send_sent_event=True,
    worker_redirect_stdouts=True,
    worker_redirect_stdouts_level=DEFAULT_LOG_LEVEL,
)
