#!/usr/bin/env python3
"""
Standalone script to simulate the webhook processing flow for a specific order.
This script mimics what the worker does when processing a Bling webhook,
allowing you to manually trigger the enrichment process for existing orders.

Usage:
    python scripts/debug_shopee_enrichment.py --order-sn 260330GSX3YH72
    python scripts/debug_shopee_enrichment.py --order-sn 260330GSX3YH72 --verbose
"""

import sys
import os
import argparse
import logging

# Add parent directory to path to import from packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nistiprint_shared.services.bling_order_processing_service import bling_order_processing_service
from nistiprint_shared.services.order_sync_service import order_sync_service
from nistiprint_shared.database.supabase_db_service import supabase_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_order_from_bling(order_sn: str):
    """
    Fetch order details from Bling API by order_sn (numeroLoja).
    Returns the full order data or None if not found.
    """
    try:
        client = bling_order_processing_service._get_bling_client_for_details()
        
        # Search by numeroLoja
        url = f"pedidos/vendas?numerosLojas[]={order_sn}"
        response = client._request('GET', url)
        
        if not response or not response.get('data'):
            logger.error(f"Pedido {order_sn} não encontrado no Bling")
            return None
        
        order_summary = response['data'][0]
        order_id = order_summary.get('id')
        
        logger.info(f"Pedido {order_sn} encontrado no Bling com ID: {order_id}")
        
        # Fetch full details
        full_order_data = client.get_order(order_id)
        if not full_order_data:
            logger.error(f"Não foi possível obter detalhes do pedido {order_id}")
            return None
        
        return full_order_data
        
    except Exception as e:
        logger.error(f"Erro ao buscar pedido no Bling: {e}", exc_info=True)
        return None


def check_if_shopee_via_erp_links(loja_id: int):
    """
    Check if the loja_id is Shopee via erp_marketplace_links.
    Returns (is_shopee, marketplace_integration_id)
    """
    try:
        erp_link_result = supabase_db.table('erp_marketplace_links') \
            .select('marketplace_integration_id') \
            .eq('erp_store_id', str(loja_id)) \
            .execute()
        
        if erp_link_result.data:
            link = erp_link_result.data[0]
            shopee_marketplace_integration_id = link.get('marketplace_integration_id')
            # marketplace_integration_id 6 = Shopee
            is_shopee = (shopee_marketplace_integration_id == 6)
            logger.info(f"Loja ID {loja_id} identificado como Shopee via erp_marketplace_links: {is_shopee}")
            return is_shopee, shopee_marketplace_integration_id
        else:
            logger.warning(f"Loja ID {loja_id} não encontrado em erp_marketplace_links")
            return False, None
            
    except Exception as e:
        logger.error(f"Erro ao verificar erp_marketplace_links: {e}", exc_info=True)
        return False, None


def check_existing_shopee_data(order_sn: str):
    """
    Check if the order already has data in pedidos_shopee table.
    """
    try:
        result = supabase_db.table('pedidos_shopee') \
            .select('codigo_pedido, informacoes_comprador, mensagem, shipping_carrier') \
            .eq('codigo_pedido', order_sn) \
            .execute()
        
        if result.data:
            data = result.data[0]
            logger.info(f"Pedido {order_sn} já existe em pedidos_shopee:")
            logger.info(f"  - buyer_username: {data.get('informacoes_comprador', {}).get('username')}")
            logger.info(f"  - mensagem: {data.get('mensagem')}")
            logger.info(f"  - shipping_carrier: {data.get('shipping_carrier')}")
            return data
        else:
            logger.info(f"Pedido {order_sn} não encontrado em pedidos_shopee")
            return None
            
    except Exception as e:
        logger.error(f"Erro ao verificar pedidos_shopee: {e}", exc_info=True)
        return None


def main():
    parser = argparse.ArgumentParser(description='Debug Shopee enrichment for a specific order')
    parser.add_argument('--order-sn', required=True, help='Shopee order SN (numeroLoja)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--skip-bling', action='store_true', help='Skip fetching from Bling API (use existing data)')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    order_sn = args.order_sn
    logger.info("=" * 60)
    logger.info(f"DEBUG SHOPEE ENRICHMENT: {order_sn}")
    logger.info("=" * 60)
    
    # Step 1: Check existing data in pedidos_shopee
    logger.info("\n[STEP 1] Checking existing data in pedidos_shopee...")
    existing_data = check_existing_shopee_data(order_sn)
    
    # Step 2: Fetch order from Bling (unless skipped)
    full_order_data = None
    loja_id = None
    
    if not args.skip_bling:
        logger.info("\n[STEP 2] Fetching order from Bling API...")
        full_order_data = get_order_from_bling(order_sn)
        
        if full_order_data:
            loja_id = full_order_data.get('loja', {}).get('id')
            logger.info(f"Loja ID: {loja_id}")
            logger.info(f"NumeroLoja: {full_order_data.get('numeroLoja')}")
            logger.info(f"Situacao: {full_order_data.get('situacao', {}).get('id')}")
        else:
            logger.error("Não foi possível buscar o pedido no Bling. Abortando.")
            return
    else:
        logger.info("\n[STEP 2] Skipped Bling API fetch (--skip-bling)")
        # Try to get loja_id from existing pedidos_bling data
        try:
            result = supabase_db.table('pedidos_bling') \
                .select('loja_id') \
                .eq('numero_loja', order_sn) \
                .execute()
            if result.data:
                loja_id = result.data[0].get('loja_id')
                logger.info(f"Loja ID from pedidos_bling: {loja_id}")
        except Exception as e:
            logger.error(f"Erro ao buscar loja_id do pedidos_bling: {e}")
    
    # Step 3: Check if it's Shopee via erp_marketplace_links
    logger.info("\n[STEP 3] Checking if order is Shopee via erp_marketplace_links...")
    if loja_id:
        is_shopee, marketplace_integration_id = check_if_shopee_via_erp_links(loja_id)
        
        if is_shopee:
            logger.info(f"✓ Pedido identificado como SHOPEE (marketplace_integration_id: {marketplace_integration_id})")
            
            # Step 4: Run sync_shopee_order
            logger.info("\n[STEP 4] Running sync_shopee_order...")
            result = order_sync_service.sync_shopee_order(
                order_sn,
                instance_id=str(marketplace_integration_id),
                marketplace_integration_id=marketplace_integration_id,
                bling_loja_id=loja_id
            )
            
            logger.info(f"Result: {result}")
            
            # Step 5: Verify the result
            logger.info("\n[STEP 5] Verifying result in pedidos_shopee...")
            updated_data = check_existing_shopee_data(order_sn)
            
            if updated_data:
                logger.info("✓ Enriquecimento concluído com sucesso!")
                
                # Check FLEX classification
                shipping_carrier = updated_data.get('shipping_carrier', '')
                if shipping_carrier and 'entrega rápida' in shipping_carrier.lower():
                    logger.info(f"✓ Pedido deve ser classificado como FLEX (carrier: {shipping_carrier})")
                else:
                    logger.info(f"  Pedido não é FLEX (carrier: {shipping_carrier})")
            else:
                logger.error("✗ Enriquecimento falhou - dados não encontrados em pedidos_shopee")
        else:
            logger.info(f"✗ Pedido não é SHOPEE (loja_id: {loja_id})")
    else:
        logger.error("Não foi possível verificar se é Shopee (loja_id não encontrado)")
    
    logger.info("\n" + "=" * 60)
    logger.info("DEBUG COMPLETE")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
