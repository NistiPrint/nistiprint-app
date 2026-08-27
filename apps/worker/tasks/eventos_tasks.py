from celery_config import celery_app
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
    Tarefa Celery que consome eventos da tabela eventos_producao_v2.

    A fila do motor legado foi aposentada no Sprint 5: existe um unico
    caminho de estoque, e ele passa por aqui.
    """
    # Configurar correlation_id
    correlation_id = with_correlation(correlation_id)
    
    try:
        # 1. Processar Eventos V2 (Event Sourcing - Dashboard)
        # IMPORTANTE: Workers Celery rodam em threads sem event loop.
        # Em Python 3.10+, asyncio.get_event_loop() levanta RuntimeError nesse caso
        # ("There is no current event loop in thread 'MainThread'").
        # Por isso criamos explicitamente um novo loop para esta execução.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            stats_v2 = loop.run_until_complete(consolidador_estoque.processar_lote())
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        # Retornar dados (o log é feito pelo decorator @log_task_execution)
        result = {
            'status': 'SUCCESS',
            'eventos_v2': stats_v2
        }

        # Otimização: Se não houver nada processado, retornar None silencia o log de sucesso do Celery
        if stats_v2.get('eventos_processados', 0) == 0:
            return None
            
        return result
    except Exception as e:
        import traceback
        print(f"[*] Erro no processador de eventos: {e}")
        traceback.print_exc()
        return {'status': 'FAILED', 'error': str(e)}
