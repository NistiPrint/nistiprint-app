import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery import shared_task
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling.bling import bling_get_order_detail, bling_get_token

logger = logging.getLogger(__name__)

BLING_BATCH_SIZE = 100
BLING_RATE_LIMIT_RPS = 3   # limite conservador por app Bling

def agendar_sync_status_batch(pedido_ids):
    """Cria o registro do lote e agenda a task Celery"""
    res = supabase_db.table('sync_status_batches').insert({
        'pedido_ids': pedido_ids,
        'total': len(pedido_ids),
        'status': 'PENDENTE',
    }).execute()
    
    if res.data:
        batch_id = res.data[0]['id']
        sync_status_batch_task.delay(batch_id)
        return batch_id
    return None

@shared_task(name='services.bling_status_sync.sync_batch', bind=True, max_retries=2)
def sync_status_batch_task(self, batch_id: str):
    """Task Celery para processar o lote de sincronização de status"""
    supabase_db.table('sync_status_batches').update({'status': 'RODANDO'}).eq('id', batch_id).execute()
    
    batch_res = supabase_db.table('sync_status_batches').select('*').eq('id', batch_id).single().execute()
    if not batch_res.data:
        logger.error(f"Batch {batch_id} não encontrado.")
        return
        
    batch = batch_res.data
    ids = batch['pedido_ids']

    # Busca os pedidos e seus links com o Bling
    pedidos_res = supabase_db.table('pedidos') \
        .select('id, pedido_bling_id, pedidos_bling(bling_id, integracao_instancia_id)') \
        .in_('id', ids).execute()
    
    if not pedidos_res.data:
        logger.warning(f"Nenhum pedido válido encontrado para o batch {batch_id}")
        supabase_db.table('sync_status_batches').update({
            'status': 'CONCLUIDO', 'finalizado_em': 'now()'
        }).eq('id', batch_id).execute()
        return

    pedidos = pedidos_res.data

    # Agrupar por instância Bling (cada uma tem token próprio + rate limit próprio)
    por_instancia = {}
    for p in pedidos:
        if p.get('pedidos_bling'):
            inst = p['pedidos_bling']['integracao_instancia_id']
            por_instancia.setdefault(inst, []).append(p)

    sucesso, falha = 0, 0
    for inst_id, lote in por_instancia.items():
        try:
            # bling_get_token espera o ID da plataforma ou instância
            token = bling_get_token(inst_id)
            if not token:
                logger.error(f"Não foi possível obter token para instância {inst_id}")
                falha += len(lote)
                continue
                
            # Paralelizar dentro do lote, mas respeitando rate limit
            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {}
                for p in lote:
                    # Spread de 1/BLING_RATE_LIMIT_RPS segundos entre disparos
                    time.sleep(max(0, (1.0/BLING_RATE_LIMIT_RPS) - 0.05))
                    futs[ex.submit(_sync_one, token, p, batch_id)] = p
                
                for fut in as_completed(futs):
                    ok = fut.result()
                    if ok: sucesso += 1
                    else:  falha += 1
                    
                    # Atualiza progresso parcialmente
                    supabase_db.table('sync_status_batches').update({
                        'sucesso': sucesso, 'falha': falha
                    }).eq('id', batch_id).execute()
        except Exception as e:
            logger.error(f"Erro ao processar lote da instância {inst_id}: {e}")
            falha += len(lote)

    supabase_db.table('sync_status_batches').update({
        'status': 'CONCLUIDO', 'finalizado_em': 'now()'
    }).eq('id', batch_id).execute()

def _sync_one(token, p, batch_id):
    """Sincroniza um único pedido"""
    bling_id = p['pedidos_bling']['bling_id']
    pedido_id = p['id']
    try:
        detail = bling_get_order_detail(token, bling_id)
        if not detail or 'data' not in detail:
             raise ValueError(f"Resposta inválida do Bling para ID {bling_id}")
             
        situacao = detail.get('data', {}).get('situacao', {})
        situacao_id = situacao.get('id')
        
        # 1. Atualiza pedidos_bling
        supabase_db.table('pedidos_bling').update({
            'situacao_id': situacao_id,
            'situacao_valor': situacao.get('valor'),
            'raw_payload': detail.get('data'),
            'updated_at': 'now()'
        }).eq('bling_id', bling_id).execute()

        # 2. Propaga para pedidos via mapping integration_status_mappings
        mapping_res = supabase_db.table('integration_status_mappings') \
            .select('situacao_pedido_id') \
            .eq('plataforma', 'bling') \
            .eq('status_externo_id', situacao_id) \
            .maybe_single().execute()
        
        if mapping_res.data:
            supabase_db.table('pedidos').update({
                'situacao_pedido_id': mapping_res.data['situacao_pedido_id'],
                'updated_at': 'now()'
            }).eq('id', pedido_id).execute()
            
        return True
    except Exception as e:
        logger.error(f"Erro ao sincronizar pedido {pedido_id} (Bling {bling_id}): {e}")
        supabase_db.table('sync_status_errors').insert({
            'batch_id': batch_id,
            'pedido_id': pedido_id,
            'bling_id': bling_id,
            'erro': str(e)[:500],
        }).execute()
        return False
