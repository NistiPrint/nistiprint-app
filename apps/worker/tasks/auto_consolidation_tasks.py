# ===========================================
# CLASSIFICAÇÃO E CONSOLIDAÇÃO AUTOMÁTICA DE PEDIDOS
# ===========================================
# Quando um novo pedido é importado via webhook Bling:
#   1. Classifica o pedido em um grupo de consolidação existente
#   2. Consolida os itens do pedido na demanda
#   3. Vincula pedido → demanda via pivot
# Se nenhum grupo existe → cria nova demanda RASCUNHO
# ===========================================

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional
import sys
import os

from celery_config import celery_app
from nistiprint_shared.services.correlation_service import with_correlation

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

# Importar supabase_db com tratamento de erro explícito
try:
    from nistiprint_shared.database.supabase_db_service import supabase_db
    print(f"[WORKER:CONSOLID] ✓ supabase_db imported successfully")
except ImportError as e:
    print(f"[WORKER:CONSOLID] ✗ FAILED to import supabase_db: {e}")
    print(f"[WORKER:CONSOLID] sys.path: {sys.path}")
    print(f"[WORKER:CONSOLID] PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}")
    raise

# ============================================================
# PREFIXO DE LOG — identificável nos logs do container
# ============================================================
_LOG_PREFIX = "[WORKER:CONSOLID]"

def _log(level: str, msg: str, **kw):
    """Log padronizado com prefixo identificável."""
    tag = f"{_LOG_PREFIX}[{level}]"
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).strftime("%H:%M:%S")
    parts = [f"{ts} {tag}", msg]
    if kw:
        parts.append(str(kw))
    line = " ".join(parts)
    print(line)


@celery_app.task(
    name="tasks.auto_consolidation_tasks.classificar_e_consolidar_pedido",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
@log_task_execution(task_type='PEDIDO')
def classificar_e_consolidar_pedido(
    self,
    pedido_id: int,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Função desativada: A consolidação automática de pedidos em demandas foi removida.
    """
    # Configurar correlation_id
    correlation_id = with_correlation(correlation_id)
    
    # Mapear pedido -> correlation_id
    try:
        supabase_db.table('entity_correlation_mapping').insert({
            'entity_type': 'pedido',
            'entity_id': pedido_id,
            'correlation_id': correlation_id
        }).execute()
    except Exception as e:
        _log("WARN", f"Erro ao mapear pedido {pedido_id} -> correlation_id: {e}")
    
    _log("INFO", f"Automação de consolidação de pedidos desativada. Pedido {pedido_id} processado sem gerar demanda.")

    return {
        "success": True,
        "pedido_id": pedido_id,
        "status": "skipped",
        "message": "Consolidação automática desativada"
    }
