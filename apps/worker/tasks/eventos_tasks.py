from celery_config import celery_app
from nistiprint_shared.services.consolidador_estoque import consolidador_estoque
from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
import asyncio

@celery_app.task(name='tasks.eventos_tasks.process_eventos_producao')
def process_eventos_producao_task():
    """
    Tarefa Celery que consome eventos da tabela eventos_producao_v2
    E também processa a fila legada (fila_processamento_estoque) para OPs e Avulsa.
    """
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
