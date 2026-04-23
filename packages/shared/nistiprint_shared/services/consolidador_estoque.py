"""
Consolidador de Estoque - Arquitetura Event Sourcing

Este é o ÚNICO processador de estoque do sistema.
Lê eventos da tabela eventos_producao_v2 e processa usando o Motor de Reconciliação.

Fluxo:
1. Lê eventos pendentes (processado = false)
2. Agrupa eventos por item_demanda_id
3. Para cada item com evento de LIQUIDACAO, executa reconciliação completa
4. Marca eventos como processados
"""

import asyncio
from decimal import Decimal
from typing import Dict, List, Any
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
from nistiprint_shared.utils.date_utils import get_now_iso


class ConsolidadorDeEstoque:
    """
    Processador de eventos de produção para reconciliação de estoque.
    """

    def __init__(self):
        self.eventos_table = supabase_db.table('eventos_producao_v2')
        self.itens_table = supabase_db.table('itens_demanda')

    async def processar_lote(self) -> Dict[str, int]:
        """
        Lê eventos não processados e executa reconciliação de estoque.
        
        Returns:
            dict: Estatísticas do processamento
        """
        stats = {
            'eventos_lidos': 0,
            'eventos_processados': 0,
            'eventos_falha': 0,
            'itens_reconciliados': 0
        }

        # 1. Obter eventos pendentes
        response = self.eventos_table.select('*').eq('processado', False).order('created_at').execute()
        eventos = response.data

        if not eventos:
            return stats

        stats['eventos_lidos'] = len(eventos)

        # 2. Agrupar eventos por item_demanda_id
        eventos_por_item: Dict[int, List[Dict]] = {}
        for evento in eventos:
            item_id = evento.get('item_demanda_id')
            if item_id:
                if item_id not in eventos_por_item:
                    eventos_por_item[item_id] = []
                eventos_por_item[item_id].append(evento)

        # 3. Processar cada item
        for item_id, eventos_item in eventos_por_item.items():
            try:
                # Verifica se há evento de LIQUIDACAO (finalização)
                tem_liquidacao = any(e.get('tipo_evento') == 'LIQUIDACAO' for e in eventos_item)
                
                if tem_liquidacao:
                    # Executa reconciliação completa do item
                    await self._reconciliar_item(item_id, eventos_item)
                    stats['itens_reconciliados'] += 1
                else:
                    # Apenas eventos SINAL (etapas intermediárias)
                    # Apenas marca como processado sem calcular estoque
                    await self._processar_sinais(eventos_item)
                
                stats['eventos_processados'] += len(eventos_item)

            except Exception as e:
                print(f"ERRO ao processar item {item_id}: {e}")
                stats['eventos_falha'] += len(eventos_item)

        return stats

    async def _reconciliar_item(self, item_id: int, eventos: List[Dict]):
        """
        Executa reconciliação de estoque para um item.
        Usa lock para evitar processamento concorrente do mesmo item.

        Args:
            item_id: ID do item de demanda
            eventos: Lista de eventos do item
        """
        # 1. Verificar lock (evita processamento concorrente)
        lock_response = self.itens_table.select('status_processamento').eq('id', item_id).execute()
        if not lock_response.data:
            raise ValueError(f"Item {item_id} não encontrado")
        
        status_proc = lock_response.data[0].get('status_processamento')
        if status_proc == 'PROCESSANDO':
            # Item já está sendo processado por outra execução
            print(f"⚠ Item {item_id} já está PROCESSANDO, pulando...")
            return
        
        # 2. Obter demanda_id
        demanda_id = eventos[0].get('demanda_id')
        if not demanda_id:
            item_response = self.itens_table.select('demanda_id').eq('id', item_id).execute()
            if item_response.data:
                demanda_id = item_response.data[0].get('demanda_id')
        
        if not demanda_id:
            raise ValueError(f"Não foi possível determinar demanda_id para item {item_id}")
        
        try:
            # 3. Marcar item como PROCESSANDO (lock)
            self.itens_table.update({'status_processamento': 'PROCESSANDO'}).eq('id', item_id).execute()
            
            # 4. Executa reconciliação usando o motor
            resultado = await motor_reconciliacao_estoque.reconcile_item(
                item_id=item_id,
                demanda_id=demanda_id,
                user_id='System'
            )
            
            if not resultado.sucesso:
                raise Exception(f"Falha na reconciliação: {resultado.erros}")
            
            # 5. Marcar eventos como processados
            evento_ids = [e['id'] for e in eventos]
            self.eventos_table.update({'processado': True}).in_('id', evento_ids).execute()
            
            # 6. Liberar lock do item
            self.itens_table.update({'status_processamento': 'PROCESSADO'}).eq('id', item_id).execute()
            
            print(f"✓ Item {item_id} reconciliado: {len(resultado.movimentos)} movimentações")
            
        except Exception as e:
            # Em caso de erro, liberar lock do item
            self.itens_table.update({'status_processamento': 'PENDENTE'}).eq('id', item_id).execute()
            raise e

    async def _processar_sinais(self, eventos: List[Dict]):
        """
        Processa eventos do tipo SINAL (etapas intermediárias).
        Apenas marca como processado, sem cálculo de estoque.
        
        Args:
            eventos: Lista de eventos SINAL
        """
        evento_ids = [e['id'] for e in eventos]
        self.eventos_table.update({'processado': True}).in_('id', evento_ids).execute()


# Singleton
consolidador_estoque = ConsolidadorDeEstoque()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    stats = loop.run_until_complete(consolidador_estoque.processar_lote())
    print(f"Processamento concluído: {stats}")
