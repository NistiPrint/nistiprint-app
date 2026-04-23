"""
Worker de Reconciliação de Estoque (Motor Deterministico)
Consome fila `fila_processamento_estoque`.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
import uuid

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
from nistiprint_shared.utils.date_utils import get_now_iso

# ============================================================
# CONFIGURAÇÕES
# ============================================================
BATCH_SIZE = 10
WORKER_ID = f"worker_{str(uuid.uuid4())}"
POLL_INTERVAL_SEGUNDOS = 5

class WorkerReconciliacaoEstoque:
    """
    Worker que utiliza exclusivamente o Motor de Reconciliação (MRE) 
    para processar movimentações de forma determinística.
    """
    
    def __init__(self):
        self.fila_table = supabase_db.table('fila_processamento_estoque')
        self.worker_id = WORKER_ID
        self.running = False
    
    async def iniciar(self):
        self.running = True
        print(f"[WORKER] {self.worker_id} (MOTOR MRE) INICIADO")
        
        while self.running:
            try:
                # Busca tarefas PENDENTES (a função RPC já está aberta para todos tipos)
                # O motor trata os tipos de operação internamente
                agora = datetime.now().isoformat()
                response = self.fila_table.select('*').in_('status', ['PENDENTE', 'ERRO']).limit(BATCH_SIZE).execute()
                
                if not response.data:
                    await asyncio.sleep(POLL_INTERVAL_SEGUNDOS)
                    continue
                
                for tarefa in response.data:
                    await self._processar_tarefa(tarefa)
                
            except Exception as e:
                print(f"[WORKER] ERRO no loop: {e}")
                await asyncio.sleep(POLL_INTERVAL_SEGUNDOS)

    async def _processar_tarefa(self, tarefa: Dict[str, Any]):
        t_id = tarefa['id']
        demanda_id = tarefa.get('demanda_id')
        item_id = tarefa.get('item_id')
        user_id = tarefa.get('user_id', 'Worker')
        
        print(f"[MRE] Processando tarefa {t_id} (Demanda: {demanda_id}, Item: {item_id})")
        
        try:
            # Marca como processando
            self.fila_table.update({'status': 'PROCESSANDO'}).eq('id', t_id).execute()
            
            # Delega para o Motor de Reconciliação
            resultado = await motor_reconciliacao_estoque.reconcile_item(
                item_id=int(item_id),
                demanda_id=int(demanda_id),
                user_id=user_id
            )
            
            if resultado.sucesso:
                self.fila_table.update({'status': 'CONCLUIDO', 'processed_at': get_now_iso()}).eq('id', t_id).execute()
            else:
                raise Exception(f"Falha MRE: {resultado.erros}")
                
        except Exception as e:
            print(f"[MRE] ERRO na tarefa {t_id}: {e}")
            self.fila_table.update({'status': 'ERRO', 'mensagem_erro': str(e)}).eq('id', t_id).execute()

