#!/usr/bin/env python3
"""
Standalone script to sweep and update all Shopee orders.
- Fetches all Shopee orders from the database
- Updates order data from Bling API
- For Shopee orders, also fetches and updates data from Shopee API
- Rate limit: 0.5 req/sec to avoid restrictions
- Detailed logging of all API calls and results

Usage:
    python scripts/sweep_shopee_orders.py
    python scripts/sweep_shopee_orders.py --limit 10  # Process first 10 orders only
"""

import sys
import os
import time
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add parent directory to path to import from packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nistiprint_shared.services.bling_order_processing_service import bling_order_processing_service
from nistiprint_shared.services.order_sync_service import order_sync_service
from nistiprint_shared.database.supabase_db_service import supabase_db

# Configure logging - explicitly configure to ensure file handler works
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Clear any existing handlers to avoid duplicates
logger.handlers.clear()

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# File handler
log_filename = f'sweep_shopee_orders_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
file_handler = logging.FileHandler(log_filename)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info(f"Logging initialized. Log file: {log_filename}")

# Rate limit: 0.5 req/sec = 2 seconds between requests
RATE_LIMIT_SECONDS = 2.0


def get_all_shopee_orders() -> List[Dict[str, Any]]:
    """
    Fetch all Shopee orders from the database.
    Uses canal_venda.slug = 'shopee' for platform identification.
    Optimized to filter at database level using RPC or direct query.
    Orders are sorted by created_at (most recent first).
    """
    try:
        logger.info("Fetching Shopee orders from database...")
        
        # Use RPC to join and filter efficiently
        try:
            result = supabase_db.rpc('get_shopee_orders').execute()
            if result.data:
                logger.info(f"Found {len(result.data)} Shopee orders via RPC")
                # Sort by created_at descending (most recent first)
                result.data.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                return result.data
        except Exception as rpc_error:
            logger.warning(f"RPC not available, falling back to manual query: {rpc_error}")
        
        # Fallback: Use a more efficient approach - fetch canal_venda IDs first
        logger.info("Fetching canais_venda with slug='shopee'...")
        canal_result = supabase_db.table('canais_venda') \
            .select('id') \
            .eq('slug', 'shopee') \
            .execute()
        
        if not canal_result.data:
            logger.error("No Shopee canal found in canais_venda")
            return []
        
        shopee_canal_ids = [c['id'] for c in canal_result.data]
        logger.info(f"Shopee canal IDs: {shopee_canal_ids}")
        
        # Now fetch orders filtering by these canal IDs, ordered by created_at desc
        logger.info("Fetching orders for Shopee canais (most recent first)...")
        orders_result = supabase_db.table('pedidos') \
            .select('id, numero_pedido, codigo_pedido_externo, canal_venda_id, created_at') \
            .in_('canal_venda_id', shopee_canal_ids) \
            .order('created_at', desc=True) \
            .execute()
        
        if not orders_result.data:
            logger.error("No orders found for Shopee canais")
            return []
        
        logger.info(f"Found {len(orders_result.data)} Shopee orders in database")
        return orders_result.data
        
    except Exception as e:
        logger.error(f"Error fetching Shopee orders: {e}", exc_info=True)
        return []


def classify_flex_from_shipping_carrier(shipping_carrier: str) -> tuple[bool, str]:
    """
    Classify if order is FLEX based on shipping_carrier field.
    Rule: if shipping_carrier contains 'entrega rapida' or 'entrega rápida', it's flex.
    
    Returns (is_flex, classification_reason)
    """
    if not shipping_carrier:
        return False, "No shipping_carrier"
    
    carrier_lower = shipping_carrier.lower()
    
    # Check for flex indicators
    if 'entrega rapida' in carrier_lower or 'entrega rápida' in carrier_lower:
        return True, f"Contains 'entrega rapida/rápida'"
    
    return False, f"No flex indicator (carrier: {shipping_carrier})"


def get_shipping_carrier_from_order(order_sn: str) -> Optional[str]:
    """
    Extract shipping_carrier from pedidos_shopee table.
    Returns the shipping_carrier value or None if not found.
    """
    try:
        result = supabase_db.table('pedidos_shopee') \
            .select('shipping_carrier') \
            .eq('codigo_pedido', order_sn) \
            .execute()
        
        if result.data:
            carrier = result.data[0].get('shipping_carrier')
            logger.debug(f"Found shipping_carrier for {order_sn}: {carrier}")
            return carrier
        else:
            logger.debug(f"No record found in pedidos_shopee for {order_sn}")
            return None
    except Exception as e:
        logger.warning(f"Error fetching shipping_carrier for {order_sn}: {e}")
        return None


def check_if_shopee_via_erp_links(loja_id: int) -> tuple[bool, int]:
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
            is_shopee = (shopee_marketplace_integration_id == 6)
            logger.debug(f"Loja ID {loja_id} identified as Shopee via erp_marketplace_links: {is_shopee}")
            return is_shopee, shopee_marketplace_integration_id
        else:
            logger.debug(f"Loja ID {loja_id} not found in erp_marketplace_links")
            return False, None
            
    except Exception as e:
        logger.error(f"Error checking erp_marketplace_links for loja_id {loja_id}: {e}")
        return False, None


def fetch_order_from_bling(order_sn: str) -> Dict[str, Any]:
    """
    Fetch order details from Bling API by order_sn (numeroLoja).
    Returns the full order data or None if not found.
    """
    try:
        logger.info(f"[BLING API] Fetching order {order_sn}...")
        
        client = bling_order_processing_service._get_bling_client_for_details()
        
        # Search by numeroLoja
        url = f"pedidos/vendas?numerosLojas[]={order_sn}"
        response = client._request('GET', url)
        
        if not response or not response.get('data'):
            logger.warning(f"[BLING API] Order {order_sn} not found")
            return None
        
        order_summary = response['data'][0]
        order_id = order_summary.get('id')
        logger.info(f"[BLING API] Order {order_sn} found with ID: {order_id}")
        
        # Fetch full details
        full_order_data = client.get_order(order_id)
        if not full_order_data:
            logger.error(f"[BLING API] Could not fetch details for order {order_id}")
            return None
        
        logger.info(f"[BLING API] Successfully fetched order {order_sn}")
        return full_order_data
        
    except Exception as e:
        logger.error(f"[BLING API] Error fetching order {order_sn}: {e}", exc_info=True)
        return None


def sync_order_from_bling(order_data: Dict[str, Any], bling_integration_id: int) -> bool:
    """
    Sync order from Bling to the unified database.
    Returns True if successful, False otherwise.
    """
    try:
        logger.info(f"[SYNC BLING] Syncing order {order_data.get('numeroLoja')} to database...")
        
        result = order_sync_service.sync_bling_order(
            order_data,
            bling_integration_id=bling_integration_id
        )
        
        if result:
            logger.info(f"[SYNC BLING] Successfully synced order {order_data.get('numeroLoja')}")
            return True
        else:
            logger.error(f"[SYNC BLING] Failed to sync order {order_data.get('numeroLoja')}")
            return False
            
    except Exception as e:
        logger.error(f"[SYNC BLING] Error syncing order {order_data.get('numeroLoja')}: {e}", exc_info=True)
        return False


def sync_order_from_shopee(order_sn: str, instance_id: str, channel_id: int, 
                          marketplace_integration_id: int, bling_loja_id: int) -> bool:
    """
    Sync order from Shopee API to the unified database.
    Returns True if successful, False otherwise.
    """
    try:
        logger.info(f"[SYNC SHOPEE] Syncing order {order_sn} from Shopee API...")
        
        # Call Shopee API directly to get raw response for debugging
        from nistiprint_shared.services.platform_api_service import platform_api_service
        from nistiprint_shared.services.installed_integration_service import installed_integration_service
        
        resolved_instance_id = instance_id or (str(marketplace_integration_id) if marketplace_integration_id else None)
        logger.info(f"[SYNC SHOPEE] Calling Shopee API with instance_id: {resolved_instance_id}")
        
        shopee_data = platform_api_service.get_order_detail([order_sn], resolved_instance_id, "shopee")
        logger.info(f"[SYNC SHOPEE] Raw API response for {order_sn}: {shopee_data}")
        
        if "error" in shopee_data and shopee_data["error"]:
            logger.error(f"[SYNC SHOPEE] Error from Shopee API for {order_sn}: {shopee_data['error']}")
        
        # Extract and log shipping_carrier from raw response
        raw_order = shopee_data.get("raw", {})
        shipping_carrier_from_api = raw_order.get('shipping_carrier', 'N/A')
        logger.info(f"[SYNC SHOPEE] shipping_carrier from API: {shipping_carrier_from_api}")
        
        # Now sync using order_sync_service
        result = order_sync_service.sync_shopee_order(
            order_sn,
            instance_id=instance_id,
            channel_id=channel_id,
            marketplace_integration_id=marketplace_integration_id,
            bling_loja_id=bling_loja_id
        )
        
        # Log complete response for debugging shipping_carrier
        logger.info(f"[SYNC SHOPEE] Sync result for {order_sn}: {result}")
        
        if result:
            logger.info(f"[SYNC SHOPEE] Successfully synced order {order_sn}")
            return True
        else:
            logger.error(f"[SYNC SHOPEE] Failed to sync order {order_sn}")
            return False
            
    except Exception as e:
        logger.error(f"[SYNC SHOPEE] Error syncing order {order_sn}: {e}", exc_info=True)
        return False


def process_order(order: Dict[str, Any], canal_config: Dict[str, Any], skip_bling: bool, skip_shopee: bool) -> Dict[str, Any]:
    """
    Process a single order:
    1. Fetch from Bling API (unless --skip-bling)
    2. Sync Bling data (unless --skip-bling)
    3. If Shopee, fetch and sync Shopee data (unless --skip-shopee)
    
    Returns result summary.
    """
    order_sn = order.get('codigo_pedido_externo')
    pedido_id = order.get('id')
    created_at = order.get('created_at', 'N/A')
    
    logger.info("=" * 80)
    logger.info(f"PROCESSING ORDER: {order_sn} (ID: {pedido_id})")
    logger.info(f"Created: {created_at}")
    logger.info(f"Skip Bling: {skip_bling}, Skip Shopee: {skip_shopee}")
    
    # Extract and classify shipping_carrier for flex detection
    shipping_carrier = get_shipping_carrier_from_order(order_sn)
    is_flex, flex_reason = classify_flex_from_shipping_carrier(shipping_carrier)
    
    logger.info(f"Shipping Carrier: {shipping_carrier or 'N/A'}")
    logger.info(f"FLEX Classification: {is_flex} - {flex_reason}")
    logger.info("=" * 80)
    
    result = {
        'order_sn': order_sn,
        'pedido_id': pedido_id,
        'bling_success': False,
        'shopee_success': False,
        'is_shopee': False,
        'error': None
    }
    
    full_order_data = None
    loja_id = None
    
    # Step 1: Fetch from Bling (unless skipped)
    if not skip_bling:
        time.sleep(RATE_LIMIT_SECONDS)  # Rate limit
        full_order_data = fetch_order_from_bling(order_sn)
        
        if not full_order_data:
            result['error'] = 'Failed to fetch from Bling'
            return result
        
        # Step 2: Sync Bling data (unless skipped)
        time.sleep(RATE_LIMIT_SECONDS)  # Rate limit
        bling_integration_id = canal_config.get('bling_integration_id')
        bling_success = sync_order_from_bling(full_order_data, bling_integration_id)
        result['bling_success'] = bling_success
        
        if not bling_success:
            result['error'] = 'Failed to sync Bling data'
            return result
        
        loja_id = full_order_data.get('loja', {}).get('id')
    else:
        # When skipping Bling, try to get loja_id from existing pedidos_bling
        logger.info(f"Skipping Bling fetch, trying to get loja_id from database...")
        try:
            pb_result = supabase_db.table('pedidos_bling') \
                .select('loja_id') \
                .eq('numero_loja', order_sn) \
                .execute()
            if pb_result.data and pb_result.data[0].get('loja_id'):
                loja_id = pb_result.data[0].get('loja_id')
                logger.info(f"Found loja_id from pedidos_bling: {loja_id}")
        except Exception as e:
            logger.warning(f"Could not get loja_id from pedidos_bling: {e}")
    
    # Step 3: Check if Shopee and sync Shopee data (unless skipped)
    if not skip_shopee and loja_id:
        is_shopee, shopee_marketplace_integration_id = check_if_shopee_via_erp_links(loja_id)
        result['is_shopee'] = is_shopee
        
        if is_shopee and shopee_marketplace_integration_id:
            logger.info(f"Order {order_sn} is Shopee (loja_id={loja_id}), fetching from Shopee API...")
            time.sleep(RATE_LIMIT_SECONDS)  # Rate limit
            shopee_success = sync_order_from_shopee(
                order_sn,
                instance_id=str(shopee_marketplace_integration_id),
                channel_id=canal_config.get('canal_venda_id'),
                marketplace_integration_id=shopee_marketplace_integration_id,
                bling_loja_id=loja_id
            )
            result['shopee_success'] = shopee_success
            
            if not shopee_success:
                result['error'] = 'Failed to sync Shopee data'
        else:
            logger.info(f"Order {order_sn} is not Shopee (loja_id: {loja_id}, is_shopee: {is_shopee})")
    elif not skip_shopee:
        logger.warning(f"Order {order_sn} has no loja_id, cannot check if Shopee")
    
    logger.info(f"RESULT for {order_sn}: Bling={result['bling_success']}, Shopee={result['shopee_success']}")
    logger.info("=" * 80)
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Sweep and update all Shopee orders')
    parser.add_argument('--limit', type=int, help='Limit number of orders to process (for testing)')
    parser.add_argument('--skip-bling', action='store_true', help='Skip Bling sync, only Shopee sync')
    parser.add_argument('--skip-shopee', action='store_true', help='Skip Shopee sync, only Bling sync')
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("SHOPEE ORDERS SWEEP STARTED")
    logger.info(f"Rate limit: {RATE_LIMIT_SECONDS}s between requests")
    logger.info(f"Limit: {args.limit if args.limit else 'No limit'}")
    logger.info(f"Skip Bling: {args.skip_bling}")
    logger.info(f"Skip Shopee: {args.skip_shopee}")
    logger.info("=" * 80)
    
    # Step 1: Get all Shopee orders
    logger.info("Step 1: Fetching Shopee orders...")
    shopee_orders = get_all_shopee_orders()
    
    if not shopee_orders:
        logger.error("No Shopee orders found. Exiting.")
        return
    
    logger.info(f"Step 1 complete: {len(shopee_orders)} orders to process")
    
    if args.limit:
        shopee_orders = shopee_orders[:args.limit]
        logger.info(f"Processing limited to {len(shopee_orders)} orders")
    
    # Step 2: Process each order
    results = []
    total = len(shopee_orders)
    success_count = 0
    error_count = 0
    
    for idx, order in enumerate(shopee_orders, 1):
        logger.info(f"\n[{idx}/{total}] Processing order...")
        
        # Get canal config for this order
        canal_venda_id = order.get('canal_venda_id')
        canal_config = None
        if canal_venda_id:
            try:
                from nistiprint_shared.services.integracao_canal_service import integracao_canal_service
                # Try to get canal config by canal_venda_id
                # For now, use default config
                canal_config = {
                    'bling_integration_id': None,  # Will be fetched from erp_marketplace_links
                    'marketplace_integration_id': None,
                    'canal_venda_id': canal_venda_id
                }
            except Exception as e:
                logger.warning(f"Could not get canal config: {e}")
        
        result = process_order(order, canal_config, args.skip_bling, args.skip_shopee)
        results.append(result)
        
        if result['error']:
            error_count += 1
        else:
            success_count += 1
    
    # Step 3: Summary
    logger.info("=" * 80)
    logger.info("SWEEP SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total orders processed: {total}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Shopee orders found: {sum(1 for r in results if r['is_shopee'])}")
    logger.info(f"Bling sync success: {sum(1 for r in results if r['bling_success'])}")
    logger.info(f"Shopee sync success: {sum(1 for r in results if r['shopee_success'])}")
    
    # Log errors
    errors = [r for r in results if r['error']]
    if errors:
        logger.info("\nERRORS:")
        for error in errors:
            logger.info(f"  - {error['order_sn']}: {error['error']}")
    
    logger.info("=" * 80)
    logger.info("SWEEP COMPLETED")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
