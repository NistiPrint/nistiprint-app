from celery_config import celery_app
from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
from nistiprint_shared.services.consolidador_estoque import consolidador_estoque
from nistiprint_shared.services.correlation_service import with_correlation
import asyncio
import sys
import os

# Adicionar diretório do worker ao path para importar task_logger
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task_logger import log_task_execution

@celery_app.task(name='tasks.eventos_tasks.process_eventos_producao')
@log_task_execution(task_type='ESTOQUE')
def process_eventos_producao_task(correlation_id=None):
    """
    Tarefa Celery que consome eventos da tabela eventos_producao_v2
    E também processa a fila legada (fila_processamento_estoque) para OPs e Avulsa.
    """
    # Configurar correlation_id
    correlation_id = with_correlation(correlation_id)
    
    try:
        # 1. Processar Eventos V2 (Event Sourcing - Dashboard)
        loop = asyncio.get_event_loop()
        stats_v2 = loop.run_until_complete(consolidador_estoque.processar_lote())
        
        # 2. Processar Fila Unificada (Legacy/OPs/Avulsa) via Motor
        stats_fila = motor_reconciliacao_estoque.processar_fila_unificada(limit=50)
        
        return {
            'status': 'SUCCESS', 
            'eventos_v2': stats_v2,
            'tarefas_fila': stats_fila
        }
    except Exception as e:
        print(f"[*] Erro no processador de eventos/fila: {e}")
        return {'status': 'FAILED', 'error': str(e)}
