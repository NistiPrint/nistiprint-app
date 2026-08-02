# ===========================================
# TASK LOGGER DECORATOR
# ===========================================
# A implementacao vive em `nistiprint_shared.utils.task_logging` para que as
# tarefas periodicas de `packages/shared` tambem possam registrar execucao —
# antes elas ficavam fora de `task_execution_logs` porque `packages/shared` nao
# importa de `apps/worker`.
#
# Este modulo permanece como ponto de import estavel para o worker.
# ===========================================

from nistiprint_shared.utils.task_logging import log_task_execution

__all__ = ["log_task_execution"]
