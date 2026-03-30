from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from celery_config import celery_app
from nistiprint_shared.services.pedidos_bling_import_service import run_fetch_pedidos_em_andamento

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.pedidos_fetch_tasks.fetch_pedidos_em_andamento",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def fetch_pedidos_em_andamento(
    self,
    dias: int = 7,
    situacao_id: int = 15,
    config_id: Optional[str] = None,
    config_ids: Optional[List[str]] = None,
    only_plataformas: Optional[List[str]] = None,
    limit_pedidos: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Importação de pedidos Em Andamento (disparo manual via API ou chamada direta).
    """
    return run_fetch_pedidos_em_andamento(
        dias=dias,
        situacao_id=situacao_id,
        config_id=config_id,
        config_ids=config_ids,
        only_plataformas=only_plataformas,
        limit_pedidos=limit_pedidos,
    )
