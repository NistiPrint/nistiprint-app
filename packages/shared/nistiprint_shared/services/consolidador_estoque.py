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

    # Tipos de evento que disparam reconciliação completa do item.
    # - LIQUIDACAO: nome canônico, deve ser preferido em código novo.
    # - BOM_RECURSIVO_APOS_DIRETO: usado por finalizar_item / finalizar_item_parcial
    #   para sinalizar que a baixa síncrona do produto direto foi feita e o restante
    #   da BOM precisa ser processado pelo motor.
    # - FINALIZACAO: alias legado eventualmente usado em fluxos antigos.
    LIQUIDATION_EVENT_TYPES = {
        'LIQUIDACAO',
        'BOM_RECURSIVO_APOS_DIRETO',
        'FINALIZACAO',
    }

    def __init__(self):
        self.eventos_table = supabase_db.table('eventos_producao_v2')
        self.itens_table = supabase_db.table('itens_demanda')

    async def processar_lote(self, item_id: int = None) -> Dict[str, int]:
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

        import os
        import uuid

        worker_id = f"worker:{os.getpid()}:{uuid.uuid4()}"
        response = supabase_db.rpc('claim_eventos_producao', {
            'p_worker_id': worker_id,
            'p_limit': 20,
            'p_lease_seconds': 300,
            'p_item_id': int(item_id) if item_id is not None else None,
        }).execute()
        claims = response.data or []
        if isinstance(claims, dict):
            claims = [claims]

        for claim in claims:
            eventos = claim.get('eventos') or []
            if not eventos:
                continue
            item_id = int(claim['item_id'])
            event_ids = [str(event['id']) for event in eventos]
            lease = {
                'worker_id': worker_id,
                'lease_token': claim['lease_token'],
                'event_ids': event_ids,
            }
            stats['eventos_lidos'] += len(eventos)
            try:
                tem_liquidacao = any(
                    e.get('tipo_evento') in self.LIQUIDATION_EVENT_TYPES for e in eventos
                )
                if tem_liquidacao:
                    correlation_id = str(next((e.get('correlation_id') for e in eventos if e.get('correlation_id')), uuid.uuid4()))
                    operation_id = str(uuid.uuid5(
                        uuid.UUID('3eebcd51-74cf-4e30-aa6c-72cc3904149e'),
                        f"{item_id}:{','.join(sorted(event_ids))}",
                    ))
                    result = await motor_reconciliacao_estoque.reconcile_item(
                        item_id=item_id,
                        demanda_id=int(claim['demanda_id']),
                        user_id='System',
                        acquire_lock=False,
                        correlation_id=correlation_id,
                        operation_id=operation_id,
                        lease=lease,
                    )
                    if not result.sucesso:
                        raise RuntimeError('; '.join(result.erros or ['reconciliação sem sucesso']))
                    stats['itens_reconciliados'] += 1
                else:
                    complete = supabase_db.rpc('complete_eventos_producao', {
                        'p_item_id': item_id,
                        'p_worker_id': worker_id,
                        'p_lease_token': claim['lease_token'],
                        'p_event_ids': event_ids,
                    }).execute()
                    if complete.data is False:
                        raise RuntimeError('RPC de conclusão de sinais retornou false')
                stats['eventos_processados'] += len(eventos)
            except Exception as exc:
                print(f"ERRO ao processar item {item_id}: {exc}")
                try:
                    supabase_db.rpc('fail_eventos_producao', {
                        'p_item_id': item_id,
                        'p_worker_id': worker_id,
                        'p_lease_token': claim['lease_token'],
                        'p_event_ids': event_ids,
                        'p_error': str(exc)[:4000],
                        'p_retry_seconds': 30,
                    }).execute()
                except Exception as fail_exc:
                    print(f"ERRO ao agendar retry do item {item_id}: {fail_exc}")
                stats['eventos_falha'] += len(eventos)

        return stats

    async def _reconciliar_item(self, item_id: int, eventos: List[Dict]):
        """
        Executa reconciliação de estoque para um item.

        Lock atômico via compare-and-set em itens_demanda.status_processamento:
            UPDATE ... SET status='PROCESSANDO' WHERE id=X AND status<>'PROCESSANDO'
            RETURNING id
        Se zero linhas retornadas, outro worker ja pegou — pula.

        Tambem faz claim atômico dos eventos (UPDATE processado=true ... WHERE
        processado=false RETURNING id) ANTES de chamar o motor, para que dois
        workers nao processem o mesmo evento simultaneamente.

        Args:
            item_id: ID do item de demanda
            eventos: Lista de eventos do item
        """
        # 1. Obter demanda_id antes do lock (precisamos para chamar motor)
        demanda_id = eventos[0].get('demanda_id')
        if not demanda_id:
            item_response = self.itens_table.select('demanda_id').eq('id', item_id).execute()
            if item_response.data:
                demanda_id = item_response.data[0].get('demanda_id')

        if not demanda_id:
            raise ValueError(f"Não foi possível determinar demanda_id para item {item_id}")

        # 2. Lock atômico: tenta marcar como PROCESSANDO somente se nao estiver.
        # Compare-and-set evita race entre dois workers concorrentes.
        try:
            claim_response = self.itens_table \
                .update({'status_processamento': 'PROCESSANDO'}) \
                .eq('id', item_id) \
                .neq('status_processamento', 'PROCESSANDO') \
                .execute()
        except Exception as e:
            print(f"ERRO ao adquirir lock do item {item_id}: {e}")
            return

        if not claim_response.data:
            # Outro worker ja esta processando este item.
            print(f"⚠ Item {item_id} já está PROCESSANDO em outro worker, pulando...")
            return

        # 3. Claim atômico dos eventos: marca como processado=true APENAS
        # os que ainda estao processado=false (evita double-consume).
        # Se outro worker ja pegou esses eventos, recebemos 0 e abortamos
        # (liberando o lock que acabamos de obter).
        evento_ids = [e['id'] for e in eventos]
        try:
            claim_eventos = self.eventos_table \
                .update({'processado': True}) \
                .in_('id', evento_ids) \
                .eq('processado', False) \
                .execute()
            eventos_claimados = claim_eventos.data or []
        except Exception as e:
            # Erro no claim — libera lock e propaga
            self.itens_table.update({'status_processamento': 'PENDENTE'}).eq('id', item_id).execute()
            raise

        if not eventos_claimados:
            # Outro worker ja consumiu todos os eventos. Libera lock.
            print(f"⚠ Eventos do item {item_id} ja consumidos por outro worker, liberando lock.")
            self.itens_table.update({'status_processamento': 'PENDENTE'}).eq('id', item_id).execute()
            return

        try:
            # 4. Executa reconciliação usando o motor.
            # acquire_lock=False: o consolidador ja gerencia o lock (compare-and-set
            # acima). Sem isso, o motor veria PROCESSANDO posto pelo proprio
            # consolidador e desistiria com erro espurio.
            resultado = await motor_reconciliacao_estoque.reconcile_item(
                item_id=item_id,
                demanda_id=demanda_id,
                user_id='System',
                acquire_lock=False,
            )

            if not resultado.sucesso:
                raise Exception(f"Falha na reconciliação: {resultado.erros}")

            # 5. Liberar lock do item (sucesso)
            self.itens_table.update({'status_processamento': 'PROCESSADO'}).eq('id', item_id).execute()

            print(f"✓ Item {item_id} reconciliado: {len(resultado.movimentos)} movimentações")

        except Exception as e:
            # Em caso de erro: reverter claim dos eventos (volta processado=false)
            # para que possam ser retentados em proxima execucao, e liberar lock.
            try:
                claimed_ids = [ev['id'] for ev in eventos_claimados]
                if claimed_ids:
                    self.eventos_table \
                        .update({'processado': False}) \
                        .in_('id', claimed_ids) \
                        .execute()
            except Exception as rollback_err:
                print(f"AVISO: falha ao reverter claim de eventos {claimed_ids}: {rollback_err}")
            self.itens_table.update({'status_processamento': 'PENDENTE'}).eq('id', item_id).execute()
            raise

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
