"""Registro de execucao de tarefas periodicas em `task_execution_logs`.

Este decorator morava apenas em `apps/worker/task_logger.py`. Como
`packages/shared` nao pode importar de `apps/worker` sem inverter a dependencia,
as tarefas periodicas que vivem aqui — `reconcile_pending`,
`process_pending_effects`, `reconcile_marketplace_lifecycle` — ficavam de fora
do registro.

O efeito pratico disso nao foi cosmetico. Em 01/08 duas dessas tarefas foram
habilitadas em `configuracoes_aplicacao` e nunca dispararam, porque o beat nao
havia sido reiniciado. Como nenhuma delas escrevia em `task_execution_logs`, o
painel nao tinha como mostrar a ausencia: 1.609 reconciliacoes e 261 efeitos
ficaram parados com `attempts = 0` e ninguem viu.

A licao embutida aqui: uma tarefa que nao registra execucao so falha de um jeito
visivel — quando quebra. Quando ela simplesmente nao roda, o silencio e
indistinguivel de sucesso.
"""
from __future__ import annotations

import logging
import json
import re
import time
import uuid
from functools import wraps

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.correlation_service import (
    get_correlation_id,
    set_correlation_id,
)
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)
_SENSITIVE_KEY = re.compile(r"token|secret|password|authorization|api.?key|credential", re.I)


def _safe_value(value, depth: int = 0):
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(key): ("[redacted]" if _SENSITIVE_KEY.search(str(key)) else _safe_value(item, depth + 1))
                for key, item in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in list(value)[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)[:300] if isinstance(value, str) else value
    return type(value).__name__


def log_task_execution(task_type: str | None = None, task_name: str | None = None):
    """Registra inicio, fim e falha da tarefa em `task_execution_logs`.

    Args:
        task_type: categoria da tarefa (ex.: 'PEDIDO', 'ESTOQUE', 'INTEGRACAO').
        task_name: nome a registrar. Por padrao usa `func.__name__`; util quando
            o nome Celery difere do nome da funcao, o que ja acontece em
            `process_pending_effects_task` x `process_pending_effects`.

    O registro nunca derruba a tarefa: toda falha de logging e engolida com log
    proprio. Observabilidade que quebra a coisa observada e pior que nenhuma.
    """

    def decorator(func):
        registered_name = task_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            correlation_id = (
                kwargs.get("correlation_id") or get_correlation_id() or str(uuid.uuid4())
            )
            set_correlation_id(correlation_id)

            entity_type = kwargs.get("entity_type")
            entity_id = kwargs.get("entity_id")
            task_request = getattr(args[0], "request", None) if args else None
            request_id = getattr(task_request, "id", None)
            delivery_info = getattr(task_request, "delivery_info", None) or {}
            integration_id = kwargs.get("integration_id") or kwargs.get("marketplace_integration_id")
            started_at = get_now_iso()
            started_clock = time.monotonic()
            started_metadata = {
                "args": json.dumps(_safe_value(args[1:] if task_request else args), ensure_ascii=False, default=str)[:500],
                "kwargs": json.dumps(_safe_value(kwargs), ensure_ascii=False, default=str)[:500],
                "entity_type": entity_type,
                "entity_id": entity_id,
                "marketplace_integration_id": integration_id,
                "execution_origin": kwargs.get("execution_origin") or "celery",
            }

            task_log_id = None
            try:
                log_res = (
                    supabase_db.table("task_execution_logs")
                    .insert(
                        {
                            "task_name": registered_name,
                            "task_type": task_type,
                            "status": "PROCESSING",
                            "correlation_id": correlation_id,
                            "started_at": started_at,
                            "marketplace_integration_id": integration_id,
                            "celery_task_id": request_id,
                            "queue_name": delivery_info.get("routing_key") or delivery_info.get("exchange"),
                            "execution_origin": kwargs.get("execution_origin") or "celery",
                            "progress_at": started_at,
                            "metadata": started_metadata,
                        }
                    )
                    .execute()
                )
                task_log_id = log_res.data[0]["id"] if log_res.data else None
            except Exception as exc:
                logger.error("Erro ao registrar inicio da tarefa %s: %s", registered_name, exc)

            if entity_type and entity_id:
                try:
                    supabase_db.table("entity_correlation_mapping").insert(
                        {
                            "entity_type": entity_type,
                            "entity_id": entity_id,
                            "correlation_id": correlation_id,
                        }
                    ).execute()
                except Exception as exc:
                    logger.error(
                        "Erro ao mapear entity %s:%s -> correlation_id: %s",
                        entity_type,
                        entity_id,
                        exc,
                    )

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                logger.error("Erro na execucao da tarefa %s: %s", registered_name, exc)
                if task_log_id:
                    try:
                        supabase_db.table("task_execution_logs").update(
                            {
                                "status": "FAILED",
                                "finished_at": get_now_iso(),
                                "duration_ms": max(0, int((time.monotonic() - started_clock) * 1000)),
                                "progress_at": get_now_iso(),
                                "error_message": str(exc)[:1000],
                            }
                        ).eq("id", task_log_id).execute()
                    except Exception as log_error:
                        logger.error(
                            "Erro ao registrar falha da tarefa %s: %s",
                            registered_name,
                            log_error,
                        )
                raise

            if task_log_id:
                try:
                    # O metadata de inicio e preservado: sobrescrever com o
                    # resultado apagava os argumentos, justamente o que se quer
                    # ver ao investigar uma execucao estranha.
                    supabase_db.table("task_execution_logs").update(
                        {
                            "status": "COMPLETED",
                            "finished_at": get_now_iso(),
                            "duration_ms": max(0, int((time.monotonic() - started_clock) * 1000)),
                            "progress_at": get_now_iso(),
                            "metadata": {**started_metadata, "result": str(result)[:500]},
                        }
                    ).eq("id", task_log_id).execute()
                except Exception as exc:
                    logger.error(
                        "Erro ao registrar sucesso da tarefa %s: %s", registered_name, exc
                    )

            return result

        return wrapper

    return decorator
