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
        
        # Persistência dos pedidos no banco unificado
        if bling_orders_data:
            print(f"💾 Iniciando persistência de {len(bling_orders_data)} pedidos no banco unificado...")
            from nistiprint_shared.services.order_service import order_service
            
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
                except Exception as upsert_error:
                    logging.error(f"Erro ao persistir pedido {order.get('numeroLoja')}: {upsert_error}")
        
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
