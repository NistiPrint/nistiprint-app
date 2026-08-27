# ===========================================
# APOSENTADO — consolidacao automatica em lote (26/08/2026)
# ===========================================
#
# Esta task chamava consolidation_service.consolidar_pedido() pedido a pedido e
# criava um rascunho por chave de consolidacao. Entre 27/06 e 16/07 produziu 39
# rascunhos, 14 deles com zero ou um pedido — a origem do "uma demanda por
# pedido". Estava desabilitada em celery_task_schedules desde 16/07.
#
# O rascunho agora nasce do clique do operador na Torre de Despacho:
#   despacho_lancar_escopo  -> monta/soma o rascunho e consolida o lote inteiro
#   despacho_publicar_demanda -> publica e carimba despachado_em
#
# O modulo continua existindo e a task continua registrada, devolvendo um no-op
# explicito. Remover o nome do registro faria um beat antigo, ou uma mensagem
# ainda na fila do Redis, morrer com NotRegistered — o que aparece como worker
# quebrado em vez de funcionalidade encerrada.

from __future__ import annotations

import logging
from typing import Any, Dict

from celery_config import celery_app

logger = logging.getLogger("auto_consolidation")

_APOSENTADA = {
    "status": "aposentada",
    "motivo": "geracao automatica de rascunho encerrada em 26/08/2026",
    "substituto": "Torre de Despacho (despacho_lancar_escopo / despacho_publicar_demanda)",
    "pedidos_processados": 0,
    "rascunhos_criados": 0,
}


@celery_app.task(
    name="tasks.auto_consolidation_tasks.consolidar_pedidos_pendentes",
    bind=True,
    max_retries=0,
)
def consolidar_pedidos_pendentes(self) -> Dict[str, Any]:
    """No-op. Rascunho e criado pelo operador na Torre de Despacho."""
    logger.info(
        "[WORKER:CONSOLID_BATCH] task aposentada; nenhum rascunho criado. "
        "Use a Torre de Despacho."
    )
    return dict(_APOSENTADA)


@celery_app.task(
    name="tasks.auto_consolidation_tasks.consolidar_pedido_individual",
    bind=True,
    max_retries=0,
)
def consolidar_pedido_individual(self, pedido_id: int) -> Dict[str, Any]:
    """No-op. Mantida pelo mesmo motivo que a task acima."""
    logger.info(
        "[WORKER:CONSOLID_BATCH] consolidacao individual aposentada; pedido=%s ignorado.",
        pedido_id,
    )
    return dict(_APOSENTADA, pedido_id=pedido_id)
