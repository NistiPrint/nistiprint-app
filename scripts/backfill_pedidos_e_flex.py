"""
Re-classifica pedidos antigos usando o novo classificador Flex.
Este script deve ser rodado após a migração de canais_venda para installed_integrations.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services import flex_classifier_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def backfill_flex_classification():
    """
    Re-classifica todos os pedidos existentes usando o novo classificador Flex.
    """
    logger.info("Iniciando backfill de classificação Flex...")
    
    # Buscar todos os pedidos com marketplace_integration_id
    pedidos = supabase_db.table('pedidos') \
        .select('id, marketplace_integration_id, pedido_shopee_id') \
        .neq('marketplace_integration_id', None) \
        .execute().data
    
    logger.info(f"Encontrados {len(pedidos)} pedidos para re-classificar")
    
    atualizados = 0
    erros = 0
    
    for pedido in pedidos:
        pedido_id = pedido['id']
        marketplace_integration_id = pedido['marketplace_integration_id']
        pedido_shopee_id = pedido['pedido_shopee_id']
        
        try:
            # Buscar dados do pedido_shopee para classificação
            if pedido_shopee_id:
                shopee_data = supabase_db.table('pedidos_shopee') \
                    .select('shipping_carrier, fulfillment_flag') \
                    .eq('id', pedido_shopee_id) \
                    .single() \
                    .execute().data
            else:
                shopee_data = None
            
            # Buscar dados do pedido_bling para servico_logistico
            pedido_bling = supabase_db.table('pedidos') \
                .select('pedido_bling_id') \
                .eq('id', pedido_id) \
                .single() \
                .execute().data
            
            servico_logistico = None
            if pedido_bling and pedido_bling.get('pedido_bling_id'):
                bling_data = supabase_db.table('pedidos_bling') \
                    .select('transporte') \
                    .eq('id', pedido_bling['pedido_bling_id']) \
                    .single() \
                    .execute().data
                if bling_data and bling_data.get('transporte'):
                    volumes = bling_data['transporte'].get('volumes', [])
                    if volumes:
                        servico_logistico = volumes[0].get('servico')
            
            # Classificar usando o novo classificador
            fields = {
                'servico_logistico': servico_logistico,
                'shipping_carrier': shopee_data.get('shipping_carrier') if shopee_data else None,
                'fulfillment_flag': shopee_data.get('fulfillment_flag') if shopee_data else None,
            }
            
            flex = flex_classifier_service.classify(
                supabase_db,
                fields=fields,
                marketplace_integration_id=marketplace_integration_id,
                log_context={'pedido_id': pedido_id},
            )
            
            # Atualizar pedido
            supabase_db.table('pedidos') \
                .update({
                    'is_flex': flex.is_flex,
                    'modalidade_logistica': flex.modalidade,
                }) \
                .eq('id', pedido_id) \
                .execute()
            
            atualizados += 1
            logger.info(f"Pedido {pedido_id}: is_flex={flex.is_flex} modalidade={flex.modalidade} ({flex.motivo})")
            
        except Exception as e:
            erros += 1
            logger.error(f"Erro ao classificar pedido {pedido_id}: {e}")
    
    logger.info(f"Backfill concluído! Atualizados: {atualizados}, Erros: {erros}")

if __name__ == '__main__':
    backfill_flex_classification()
