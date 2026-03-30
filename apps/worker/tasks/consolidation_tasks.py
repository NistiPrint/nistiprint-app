import os
from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
import pandas as pd
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)


@celery_app.task(
    name='tasks.consolidation_tasks.process_consolidacao',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def process_consolidacao(self, consolidacao_id: int):
    """
    Task Celery para processar consolidação de pedidos de forma assíncrona.
    """
    try:
        # Busca registro da consolidação
        response = supabase_db.table('consolidacoes_pedido').select('*').eq('id', consolidacao_id).execute()
        
        if not response.data:
            raise ValueError(f"Consolidação {consolidacao_id} não encontrada")
        
        consolidacao = response.data[0]
        
        # Atualiza status para PROCESSANDO
        supabase_db.table('consolidacoes_pedido').update({
            'status': 'PROCESSANDO',
            'processing_started_at': get_now_iso()
        }).eq('id', consolidacao_id).execute()
        
        print(f"[*] Consolidacao Worker: Iniciando processamento de {consolidacao_id}")
        
        # Extrai dados do registro
        plataforma = consolidacao['platform']
        channel_id = consolidacao['channel_id']
        filepath = consolidacao['file_path']
        options = consolidacao.get('options', {})
        
        # Prepara period filter
        period_filter = {
            'start': pd.to_datetime(consolidacao.get('period_filter_start')),
            'end': pd.to_datetime(consolidacao.get('period_filter_end'))
        }
        
        # Importa processadores
        from nistiprint_shared.services.file_processors import process_mercadolivre, process_shopee, process_amazon, process_shein
        from utils import prepare_ml_file
        from nistiprint_shared.services.bling.bling_client import BlingClient
        from nistiprint_shared.services.canal_venda_service import canal_venda_service
        from nistiprint_shared.services.integration_routing_service import integration_routing_service
        
        # Busca canal
        all_channels = canal_venda_service.get_all()
        channel = next((c for c in all_channels if c.get('id') == channel_id), None)
        
        if not channel:
            raise ValueError(f"Canal {channel_id} não encontrado")
        
        # Cria BlingClient
        account_id = integration_routing_service.get_account_id(
            function_name='ORDER_IMPORT',
            module='bling',
            channel_id=channel_id,
            platform_name=plataforma
        )
        
        bling_client = BlingClient.create_client_for_platform(
            plataforma,
            channel_id=channel_id,
            function_name='ORDER_IMPORT'
        )
        
        # Processa arquivo conforme plataforma
        plataforma_normalized = plataforma.replace(' ', '').lower()
        
        if plataforma_normalized == 'mercadolivre':
            new_file_path = prepare_ml_file(filepath)
            result = process_mercadolivre(new_file_path, period_filter, options, bling_client)
            os.remove(new_file_path)
        elif 'shopee' in plataforma_normalized:
            result = process_shopee(filepath, period_filter, options, bling_client)
        elif plataforma_normalized == 'amazon':
            result = process_amazon(filepath, period_filter, options, bling_client)
        elif plataforma_normalized == 'shein':
            result = process_shein(filepath, period_filter, options, bling_client)
        else:
            raise ValueError(f"Plataforma '{plataforma}' não suportada")
        
        capas, total_capas, miolos, total_miolos, capas_miolos, ids_pedidos, total_pedidos_plataforma, bling_orders_id, bling_orders_data, bling_orders_id_numero, bling_orders_not_found, raw_data = result
        
        # Verificação de conflitos
        from nistiprint_shared.services.order_tracker_service import order_tracker_service
        
        all_orders_to_check = []
        if hasattr(capas_miolos, 'iterrows'):
            for idx, row in capas_miolos.iterrows():
                refs = row.get('order_refs', [])
                sku = str(row.get('SKU', ''))
                for ref in refs:
                    all_orders_to_check.append({
                        'pedido_externo_id': str(ref),
                        'sku_externo': sku
                    })
            
            # Remove coluna order_refs se existir
            if 'order_refs' in capas_miolos.columns:
                display_capas_miolos = capas_miolos.drop(columns=['order_refs'])
            else:
                display_capas_miolos = capas_miolos
        else:
            display_capas_miolos = capas_miolos
        
        conflicts = order_tracker_service.check_conflicts(all_orders_to_check, plataforma)
        
        # Persistência dos pedidos no banco unificado (Bacth Mode)
        if bling_orders_data:
            print(f"💾 Preparando persistência em lote de {len(bling_orders_data)} pedidos...")
            from nistiprint_shared.services.order_service import order_service
            
            # Nota: O OrderService atual não possui um método batch_upsert robusto que gerencie
            # vínculos e itens simultaneamente. Para não quebrar a lógica complexa de mappers,
            # vamos manter o loop mas reduzir o overhead de logs e garantir que o serviço trate.
            # Em uma melhoria futura, o order_service deve ganhar um método .batch_upsert()
            
            success_count = 0
            for order in bling_orders_data:
                try:
                    order_to_upsert = {
                        'codigo_pedido_externo': str(order.get('numeroLoja')),
                        'numero_pedido': str(order.get('numero')),
                        'cliente_nome': order.get('contato', {}).get('nome'),
                        'cliente_documento': order.get('contato', {}).get('numeroDocumento'),
                        'status_original': str(order.get('situacao', {}).get('id', 'IMPORTADO')),
                        'total_pedido': float(order.get('totalProdutos', 0)),
                        'origem': plataforma
                    }
                    
                    order_items = []
                    for item in order.get('itens', []):
                        order_items.append({
                            'sku_externo': item.get('codigo'),
                            'descricao': item.get('descricao'),
                            'quantidade': item.get('quantidade'),
                            'preco_unitario': item.get('valor')
                        })
                    
                    order_service.upsert_order(
                        order_data=order_to_upsert,
                        platform=plataforma,
                        platform_order_id=str(order.get('numeroLoja')),
                        raw_payload=order,
                        items=order_items,
                        channel_id=channel_id,
                        integration_id=account_id
                    )
                    success_count += 1
                except Exception as upsert_error:
                    logging.error(f"Erro ao persistir pedido {order.get('numeroLoja')}: {upsert_error}")
            
            print(f"✅ {success_count} pedidos persistidos com sucesso.")
        
        # Prepara resultado para armazenar
        # Adiciona order_refs como campo separado para exibição no frontend
        if hasattr(display_capas_miolos, 'copy'):
            display_capas_miolos_with_refs = display_capas_miolos.copy()
        else:
            display_capas_miolos_with_refs = display_capas_miolos
            
        # Re-adiciona order_refs se existir no capas_miolos original
        if hasattr(capas_miolos, 'iterrows') and 'order_refs' in capas_miolos.columns:
            # Recria o order_refs a partir do original
            order_refs_list = []
            for idx, row in capas_miolos.iterrows():
                refs = row.get('order_refs', [])
                order_refs_list.append(refs if refs else None)
            
            # Adiciona como nova coluna
            display_capas_miolos_with_refs = display_capas_miolos_with_refs.copy()
            display_capas_miolos_with_refs['order_refs'] = order_refs_list

        results = {
            plataforma: {
                'total_capas': total_capas,
                'total_miolos': total_miolos,
                'capas_data': capas.where(pd.notnull(capas), None).to_dict('records') if hasattr(capas, 'to_dict') else capas,
                'miolos_data': miolos.where(pd.notnull(miolos), None).to_dict('records') if hasattr(miolos, 'to_dict') else miolos,
                'capas_miolos_data': display_capas_miolos_with_refs.where(pd.notnull(display_capas_miolos_with_refs), None).to_dict('records') if hasattr(display_capas_miolos_with_refs, 'to_dict') else display_capas_miolos_with_refs,
                'ids_pedidos': ids_pedidos,
                'total_pedidos_plataforma': total_pedidos_plataforma,
                'bling_orders_id': bling_orders_id,
                'bling_orders_data': bling_orders_data,
                'bling_orders_id_numero': bling_orders_id_numero,
                'bling_orders_not_found': bling_orders_not_found,
                'raw_data': raw_data.where(pd.notnull(raw_data), None).to_dict('records') if hasattr(raw_data, 'to_dict') else raw_data,
                'options': options,
                'conflicts': conflicts
            }
        }
        
        # Remove arquivo temporário
        if os.path.exists(filepath):
            os.remove(filepath)
        
        # Atualiza registro com resultado
        supabase_db.table('consolidacoes_pedido').update({
            'status': 'PRONTO',
            'result_data': results,
            'processing_completed_at': get_now_iso()
        }).eq('id', consolidacao_id).execute()
        
        print(f"[*] Consolidacao Worker: {consolidacao_id} processada com sucesso!")

        # --- NOVO: DISPARAR SINCRONIZAÇÃO DE NÚMEROS BLING ---
        if ids_pedidos:
            try:
                # ids_pedidos pode vir como uma lista de IDs [id1, id2...] ou chunks [id1;id2, id101;id102...]
                # dependendo da plataforma. Vamos garantir que extraímos uma lista flat de IDs individuais.
                flat_ids = []
                if isinstance(ids_pedidos, list):
                    for item in ids_pedidos:
                        if isinstance(item, str) and ';' in item:
                            # Se for chunk de string (formato generate_ids_chunks)
                            flat_ids.extend(item.split(';'))
                        elif isinstance(item, (str, int)):
                            # Se for ID individual
                            flat_ids.append(str(item))
                
                # Remover duplicatas e filtrar strings vazias
                flat_ids = list(set([str(fid) for fid in flat_ids if fid]))
                
                if flat_ids:
                    print(f"[*] Consolidacao Worker: Disparando sync de {len(flat_ids)} pedidos individuais com Bling...")
                    celery_app.send_task(
                        'tasks.consolidation_tasks.sync_orders_with_bling',
                        args=[flat_ids, channel_id, plataforma],
                        kwargs={}
                    )
            except Exception as sync_trigger_err:
                print(f"⚠️ Erro ao disparar sync com Bling: {sync_trigger_err}")
        # ----------------------------------------------------
        
        return {'status': 'SUCCESS', 'consolidacao_id': consolidacao_id}
        
    except Exception as e:
        logger.error(f"Error processing consolidacao {consolidacao_id}: {e}")
        
        # Atualiza status para ERRO
        supabase_db.table('consolidacoes_pedido').update({
            'status': 'ERRO',
            'error_message': str(e),
            'processing_completed_at': get_now_iso()
        }).eq('id', consolidacao_id).execute()
        
        # Tenta remover arquivo temporário se existir
        try:
            response = supabase_db.table('consolidacoes_pedido').select('file_path').eq('id', consolidacao_id).execute()
            if response.data:
                filepath = response.data[0].get('file_path')
                if filepath and os.path.exists(filepath):
                    os.remove(filepath)
        except:
            pass
        
        print(f"[*] Consolidacao Worker Error: {e}")
        self.retry(exc=e)
        return {'status': 'FAILED', 'error': str(e)}


@celery_app.task(
    name='tasks.consolidation_tasks.sync_orders_with_bling',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def sync_orders_with_bling(self, order_numbers: list, channel_id: int, platform: str):
    """
    Busca os números reais dos pedidos no Bling e atualiza o banco de dados.
    """
    if not order_numbers:
        return {'status': 'SKIPPED', 'reason': 'No order numbers provided'}

    print(f"[*] Sync Bling Worker: Iniciando sincronização de {len(order_numbers)} pedidos ({platform})")
    
    task_log_id = None
    try:
        from nistiprint_shared.services.bling.bling_client import BlingClient
        from nistiprint_shared.services.order_service import order_service
        from nistiprint_shared.database.supabase_db_service import supabase_db

        # Registrar início da tarefa
        log_res = supabase_db.table('task_execution_logs').insert({
            'task_name': 'sync_orders_with_bling',
            'status': 'PROCESSING',
            'started_at': get_now_iso(),
            'metadata': {
                'channel_id': channel_id,
                'platform': platform,
                'order_count': len(order_numbers)
            }
        }).execute()
        
        if log_res.data:
            task_log_id = log_res.data[0]['id']

        # 1. Criar cliente Bling
        bling_client = BlingClient.create_client_for_platform(
            platform,
            channel_id=channel_id,
            function_name='ORDER_IMPORT'
        )

        # 2. Buscar mapeamento (otimizado)
        mappings = bling_client.get_order_numbers_by_store_numbers(order_numbers)
        
        if not mappings:
            print(f"[*] Sync Bling Worker: Nenhum pedido encontrado no Bling.")
            if task_log_id:
                supabase_db.table('task_execution_logs').update({
                    'status': 'COMPLETED',
                    'finished_at': get_now_iso(),
                    'metadata': {
                        'channel_id': channel_id,
                        'platform': platform,
                        'order_count': len(order_numbers),
                        'found_count': 0
                    }
                }).eq('id', task_log_id).execute()
            return {'status': 'SUCCESS', 'found': 0}

        # 3. Atualizar cada pedido
        updated_count = 0
        for mapping in mappings:
            try:
                order_data = {
                    'codigo_pedido_externo': str(mapping['numeroLoja']),
                    'numero_pedido': str(mapping['numero']),
                    'origem': platform
                }
                
                order_service.upsert_order(
                    order_data=order_data,
                    platform='BLING',
                    platform_order_id=str(mapping['numeroLoja']),
                    raw_payload={'bling_mapping': mapping}
                )
                updated_count += 1
            except Exception as e:
                print(f"⚠️ Erro ao atualizar pedido {mapping['numeroLoja']}: {e}")

        # Finalizar log
        if task_log_id:
            supabase_db.table('task_execution_logs').update({
                'status': 'COMPLETED',
                'finished_at': get_now_iso(),
                'metadata': {
                    'channel_id': channel_id,
                    'platform': platform,
                    'order_count': len(order_numbers),
                    'found_count': len(mappings),
                    'updated_count': updated_count
                }
            }).eq('id', task_log_id).execute()

        print(f"[*] Sync Bling Worker: Sincronização concluída. {updated_count} pedidos atualizados.")
        return {'status': 'SUCCESS', 'updated': updated_count}

    except Exception as e:
        logger.error(f"Error syncing orders with Bling: {e}")
        if task_log_id:
            try:
                supabase_db.table('task_execution_logs').update({
                    'status': 'FAILED',
                    'finished_at': get_now_iso(),
                    'error_message': str(e)
                }).eq('id', task_log_id).execute()
            except: pass
        self.retry(exc=e)
        return {'status': 'FAILED', 'error': str(e)}


@celery_app.task(
    name='tasks.consolidation_tasks.persist_orders_batch',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def persist_orders_batch(self, json_file_path: str, platform: str, channel_id: int, account_id: str):
    """
    Task dedicada para persistir pedidos em lote no banco unificado a partir de um JSON temporário.
    Isso alivia o endpoint síncrono.
    """
    import json
    import os
    from nistiprint_shared.services.order_service import order_service
    import logging
    
    logger = logging.getLogger(__name__)

    print(f"[*] Persist Worker: Iniciando persistência assíncrona para {platform}...")
    
    if not os.path.exists(json_file_path):
        return {'status': 'FAILED', 'error': 'JSON file not found'}
        
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            bling_orders_data = data.get('orders', [])
            
        if not bling_orders_data:
            print("[*] Persist Worker: Lista de pedidos vazia.")
            if os.path.exists(json_file_path):
                os.remove(json_file_path)
            return {'status': 'SKIPPED', 'count': 0}

        success_count = 0
        error_count = 0
        
        for order in bling_orders_data:
            try:
                # Normalização básica para o OrderService
                order_to_upsert = {
                    'codigo_pedido_externo': str(order.get('numeroLoja')),
                    'numero_pedido': str(order.get('numero')),
                    'cliente_nome': order.get('contato', {}).get('nome'),
                    'cliente_documento': order.get('contato', {}).get('numeroDocumento'),
                    'status_original': str(order.get('situacao', {}).get('id', 'IMPORTADO')),
                    'total_pedido': float(order.get('totalProdutos', 0)),
                    'origem': platform
                }
                
                order_items = []
                for item in order.get('itens', []):
                    order_items.append({
                        'sku_externo': item.get('codigo'),
                        'descricao': item.get('descricao'),
                        'quantidade': item.get('quantidade'),
                        'preco_unitario': item.get('valor')
                    })

                order_service.upsert_order(
                    order_data=order_to_upsert,
                    platform=platform,
                    platform_order_id=str(order.get('numeroLoja')),
                    raw_payload=order,
                    items=order_items,
                    channel_id=channel_id,
                    integration_id=account_id
                )
                success_count += 1
            except Exception as item_err:
                error_count += 1
                logger.error(f"Erro ao persistir pedido individual no worker: {item_err}")

        print(f"✅ Persist Worker: {success_count} processados, {error_count} falhas. Limpando arquivo.")
        
        # Cleanup
        if os.path.exists(json_file_path):
            os.remove(json_file_path)
        
        return {'status': 'SUCCESS', 'processed': success_count, 'errors': error_count}
        
    except Exception as e:
        logger.error(f"Erro fatal no worker de persistência: {e}")
        # Tenta remover arquivo mesmo em erro
        if os.path.exists(json_file_path):
            os.remove(json_file_path)
        self.retry(exc=e)
        return {'status': 'FAILED', 'error': str(e)}
