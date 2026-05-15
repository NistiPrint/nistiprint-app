# ===========================================
# CLASSIFICAÇÃO E CONSOLIDAÇÃO AUTOMÁTICA DE PEDIDOS (LOTE)
# ===========================================
# Tarefa periódica que processa pedidos pendentes de consolidação.
# ===========================================

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional
import sys
import os
import logging

from celery_config import celery_app
from nistiprint_shared.services.correlation_service import with_correlation, generate_correlation_id

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

# Importar supabase_db e consolidation_service com tratamento de erro
try:
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.consolidation_service import consolidation_service
    print(f"[WORKER:CONSOLID] ✓ services imported successfully")
except ImportError as e:
    print(f"[WORKER:CONSOLID] ✗ FAILED to import services: {e}")
    raise

logger = logging.getLogger("auto_consolidation")

# ============================================================
# PREFIXO DE LOG — identificável nos logs do container
# ============================================================
_LOG_PREFIX = "[WORKER:CONSOLID_BATCH]"

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
    name="tasks.auto_consolidation_tasks.consolidar_pedidos_pendentes",
    bind=True,
    max_retries=1,
)
@log_task_execution(task_type='SISTEMA')
def consolidar_pedidos_pendentes(self) -> Dict[str, Any]:
    """
    Busca pedidos que ainda não foram consolidados em demandas e tenta processá-los.
    Ignora pedidos marcados como 'não classificados' que ainda não foram resolvidos.
    """
    correlation_id = generate_correlation_id()
    _log("INFO", "Iniciando tarefa de consolidação de pedidos pendentes", correlation_id=correlation_id)

    try:
        # 1. Buscar pedidos pendentes (has_demanda = false)
        # Filtramos também para evitar pedidos que já falharam (unresolved em pedidos_nao_classificados)
        query = (
            supabase_db.table('view_pedidos_para_consolidar')
            .select('pedido_id')
            .eq('has_demanda', False)
            .limit(50) # Processar em lotes de 50
        )
        
        # Como a view_pedidos_para_consolidar não faz join com pedidos_nao_classificados,
        # fazemos a filtragem manual ou via uma subconsulta se possível.
        # Infelizmente o PostgREST simplificado dificulta subconsultas complexas via Python client sem RPC.
        # Vamos buscar os IDs e filtrar os que estão bloqueados.
        
        response = query.execute()
        pedidos_view = response.data or []
        
        if not pedidos_view:
            _log("INFO", "Nenhum pedido pendente de consolidação encontrado.")
            return {"status": "success", "processed": 0}

        pedido_ids = [p['pedido_id'] for p in pedidos_view]
        
        # 2. Filtrar pedidos que estão na lista de 'não classificados' e não foram resolvidos
        pnc_response = (
            supabase_db.table('pedidos_nao_classificados')
            .select('pedido_id')
            .in_('pedido_id', pedido_ids)
            .eq('resolvido', False)
            .execute()
        )
        pedidos_bloqueados = {row['pedido_id'] for row in (pnc_response.data or [])}
        
        pedidos_para_processar = [pid for pid in pedido_ids if pid not in pedidos_bloqueados]
        
        if not pedidos_para_processar:
            _log("INFO", "Todos os pedidos encontrados estão bloqueados por falta de classificação.")
            return {"status": "success", "processed": 0, "blocked": len(pedidos_bloqueados)}

        # 3. Processar cada pedido
        success_count = 0
        fail_count = 0
        
        for pid in pedidos_para_processar:
            try:
                # Usamos o mesmo correlation_id para o lote
                resultado = consolidation_service.consolidar_pedido(pid)
                if resultado:
                    success_count += 1
                else:
                    # Se retornar None, consolidation_service já sinalizou em pedidos_nao_classificados
                    fail_count += 1
            except Exception as e:
                _log("ERROR", f"Erro ao consolidar pedido {pid}: {e}")
                fail_count += 1

        _log("INFO", f"Finalizado: {success_count} sucessos, {fail_count} falhas.", processed=len(pedidos_para_processar))

        return {
            "status": "success",
            "processed": len(pedidos_para_processar),
            "success": success_count,
            "failed": fail_count,
            "blocked": len(pedidos_bloqueados)
        }

    except Exception as e:
        _log("ERROR", f"Falha na task de consolidação em lote: {e}")
        return {"status": "error", "message": str(e)}


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
    Função mantida para compatibilidade, mas redireciona para o consolidation_service.
    Pode ser usada para forçar a consolidação de um pedido específico.
    """
    correlation_id = with_correlation(correlation_id)
    
    try:
        resultado = consolidation_service.consolidar_pedido(pedido_id)
        if resultado:
            return {
                "success": True,
                "pedido_id": pedido_id,
                "status": "consolidated",
                "demanda_id": resultado.get('id')
            }
        else:
            return {
                "success": False,
                "pedido_id": pedido_id,
                "status": "not_classified",
                "message": "Pedido não pôde ser classificado e foi sinalizado."
            }
    except Exception as e:
        _log("ERROR", f"Erro na consolidação forçada do pedido {pedido_id}: {e}")
        return {
            "success": False,
            "pedido_id": pedido_id,
            "status": "error",
            "message": str(e)
        }
