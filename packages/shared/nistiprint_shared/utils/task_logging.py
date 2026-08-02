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
import uuid
from functools import wraps

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.correlation_service import (
    get_correlation_id,
    set_correlation_id,
)
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)


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
            started_metadata = {
                "args": str(args)[:500],
                "kwargs": str(kwargs)[:500],
                "entity_type": entity_type,
                "entity_id": entity_id,
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
                            "started_at": get_now_iso(),
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
