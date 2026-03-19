from nistiprint_shared.database.supabase_db_service import supabase_db, get_db_session
from nistiprint_shared.models.demanda_item_origem import DemandaItemOrigem
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging


class OrderTrackerService:
    """
    Service responsible for verifying duplication of external orders.
    Enforces the 'at least once' processing guarantee by tracking individual items.
    """

    def __init__(self):
        self.demandas_item_origem_table = supabase_db.table('demandas_item_origem')

    def normalize_platform_name(self, platform: str) -> str:
        """Normalizes platform name to a standard format."""
        if not platform:
            return "Unknown"
        
        p = platform.lower().strip()
        if 'shopee' in p: return 'Shopee'
        if 'mercado' in p and 'livre' in p: return 'MercadoLivre'
        if 'amazon' in p: return 'Amazon'
        if 'shein' in p: return 'Shein'
        if 'bling' in p: return 'Bling'
        return platform.title()

    def check_conflicts(self, orders_list: List[Dict[str, Any]], platform: str) -> List[Dict[str, Any]]:
        """
        Checks for orders that have already been processed and returns conflict details.

        Args:
            orders_list: List of dictionaries with 'pedido_externo_id' and 'items'.
            platform: Platform name.

        Returns:
            List of conflict objects: {
                'pedido_externo_id': str,
                'sku_externo': str,
                'quantidade_atendida': int,
                'demanda_id': int,
                'demanda_nome': str
            }
        """
        if not orders_list:
            return []

        norm_platform = self.normalize_platform_name(platform)
        order_ids = list(set(order.get('pedido_externo_id') for order in orders_list if order.get('pedido_externo_id')))

        if not order_ids:
            return []

        try:
            # Query using Supabase client with join
            response = supabase_db.table('demandas_item_origem').select("""
                pedido_externo_id,
                sku_externo,
                quantidade_atendida,
                demanda_item_id,
                itens_demanda!inner(
                    demanda_id,
                    demandas_producao(
                        id,
                        descricao
                    )
                )
            """).eq('plataforma', norm_platform).in_('pedido_externo_id', order_ids).execute()

            if not response.data:
                return []

            # Flatten the nested response
            conflicts = []
            for record in response.data:
                demanda_item = record.get('itens_demanda')
                if demanda_item:
                    demanda = demanda_item.get('demandas_producao')
                    if demanda:
                        conflicts.append({
                            'pedido_externo_id': record['pedido_externo_id'],
                            'sku_externo': record['sku_externo'],
                            'quantidade_atendida': record['quantidade_atendida'],
                            'demanda_id': demanda['id'],
                            'demanda_nome': demanda['descricao']
                        })

            return conflicts

        except Exception as e:
            logging.error(f"Error checking conflicts: {e}")
            return []

    def filter_processed_items(self, orders_list: List[Dict[str, Any]], platform: str) -> List[Dict[str, Any]]:
        """
        Filters out items that have already been processed based on the external order ID.
        
        Args:
            orders_list: List of dictionaries. Each dict MUST have:
                         - 'pedido_externo_id': The unique Order ID (e.g., order_sn, order_id)
                         - 'items': List of item dicts, each with 'sku_externo' (and optional 'item_externo_id')
            platform: The platform name.
            
        Returns:
            List of orders containing ONLY the items that haven't been fully processed yet.
            If an order has 0 remaining items, it is excluded from the return list.
        """
        if not orders_list:
            return []

        norm_platform = self.normalize_platform_name(platform)
        
        # 1. Extract IDs to query in batch
        order_ids = list(set(order.get('pedido_externo_id') for order in orders_list if order.get('pedido_externo_id')))
        
        if not order_ids:
            return orders_list  # No IDs to check, assume new or invalid

        # 2. Query existing records
        try:
            # Note: Supabase 'in_' filter limit might apply. For huge lists, might need chunking.
            # Assuming reasonable batch sizes (e.g., < 100 orders).
            response = self.demandas_item_origem_table.select("*")\
                .eq('plataforma', norm_platform)\
                .in_('pedido_externo_id', order_ids)\
                .execute()
            
            existing_records = response.data or []
            
            # Map existing processed quantities: (order_id, sku, item_id) -> total_processed_qty
            processed_map = {}
            for record in existing_records:
                # Key includes item_externo_id if available to be specific, otherwise fallback to SKU
                key = (
                    str(record['pedido_externo_id']),
                    str(record.get('item_externo_id') or ''),
                    str(record.get('sku_externo') or '')
                )
                processed_map[key] = processed_map.get(key, 0) + int(record['quantidade_atendida'])

            new_orders = []
            
            for order in orders_list:
                order_id = str(order.get('pedido_externo_id', ''))
                items_to_process = []
                
                for item in order.get('items', []):
                    sku = str(item.get('sku_externo') or item.get('sku') or '')
                    item_id = str(item.get('item_externo_id') or '')
                    qty_requested = int(item.get('quantidade', 1))
                    
                    key = (order_id, item_id, sku)
                    qty_already_processed = processed_map.get(key, 0)
                    
                    # If we haven't processed the full quantity yet, include it
                    if qty_already_processed < qty_requested:
                        remaining_qty = qty_requested - qty_already_processed
                        
                        # Clone item to modify quantity
                        item_copy = item.copy()
                        item_copy['quantidade'] = remaining_qty
                        # Flag to indicate this is a partial fulfillment if needed
                        item_copy['_original_quantity'] = qty_requested
                        
                        items_to_process.append(item_copy)
                
                if items_to_process:
                    order_copy = order.copy()
                    order_copy['items'] = items_to_process
                    new_orders.append(order_copy)
                    
            return new_orders

        except Exception as e:
            logging.error(f"Error filtering processed items: {e}")
            # Fail safe: return original list but log error. 
            # Ideally should verify why it failed to avoid duplication.
            return orders_list

    def _ensure_order_record(self, pedido_externo_id: str, platform: str, session: Any):
        """
        Ensures a record exists in the 'public.pedidos' table for this external order.
        Acts as the centralized order registry.
        """
        norm_platform = self.normalize_platform_name(platform)

        try:
            # Check if exists using Supabase
            response = supabase_db.table('pedidos').select('id').eq('codigo_pedido_externo', pedido_externo_id).eq('origem', norm_platform).execute()

            if response.data:
                return

            # Insert basic record if missing
            import uuid
            new_order = {
                'uuid_pedido': str(uuid.uuid4()),
                'codigo_pedido_externo': pedido_externo_id,
                'origem': norm_platform,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            supabase_db.table('pedidos').insert(new_order).execute()

        except Exception as e:
            logging.error(f"Error ensuring order record: {e}")

    def register_processed_items(self, demanda_id: int, orders_list: List[Dict[str, Any]], platform: str):
        """
        Registers processed items in the DemandaItemOrigem table.
        This "locks" the items so they aren't processed again.
        
        Args:
            demanda_id: The internal demand ID just created.
            orders_list: The list of orders (and items) that generated this demand.
                         These should be the *filtered* orders (what was actually used).
            platform: Platform name.
        """
        if not orders_list or not demanda_id:
            return

        norm_platform = self.normalize_platform_name(platform)

        try:
            from nistiprint_shared.services.demanda.core import demanda_core_service

            # 1. Fetch the created demand and its items
            demanda = demanda_core_service.get_demanda_with_itens(demanda_id)
            if not demanda or 'itens' not in demanda:
                logging.warning(f"Demanda {demanda_id} not found or has no items.")
                return

            # 2. Map Demanda Items: (sku, product_id) -> list of Item IDs
            # A demand might have multiple lines for same SKU (rare but possible), so we use a list
            # Ideally, demand creation aggregates same SKUs.
            demanda_items_map = {}
            for d_item in demanda['itens']:
                # Key: SKU is the most reliable link between external and internal at this stage
                key_sku = str(d_item.get('sku') or '').strip()
                # Also map by Product ID if available
                key_pid = str(d_item.get('produto_id') or '')
                
                if key_sku:
                    if key_sku not in demanda_items_map: demanda_items_map[key_sku] = []
                    demanda_items_map[key_sku].append(d_item)
                
                # Fallback key using product_id if SKU is missing/internal
                if key_pid and key_pid != 'None':
                     if key_pid not in demanda_items_map: demanda_items_map[key_pid] = []
                     demanda_items_map[key_pid].append(d_item)

            records_to_insert = []
            
            for order in orders_list:
                order_id = str(order.get('pedido_externo_id', ''))
                
                for item in order.get('items', []):
                    sku_externo = str(item.get('sku_externo') or item.get('sku') or '').strip()
                    item_externo_id = str(item.get('item_externo_id') or '')
                    qty = int(item.get('quantidade', 0))
                    product_id = str(item.get('produto_id') or '') # Internal resolved ID
                    
                    if qty <= 0: continue

                    # Find matching demand item
                    # Strategy: Try SKU match first, then Product ID match
                    candidates = demanda_items_map.get(sku_externo)
                    if not candidates and product_id:
                        candidates = demanda_items_map.get(product_id)
                    
                    target_demanda_item_id = None
                    
                    if candidates:
                        # Simple logic: take the first candidate that still "needs" attribution?
                        # Or just point to the first one. Since demand aggregates, one demand item 
                        # can represent multiple external items.
                        target_demanda_item_id = candidates[0]['id']
                    
                    if target_demanda_item_id:
                        records_to_insert.append({
                            'demanda_item_id': target_demanda_item_id,
                            'plataforma': norm_platform,
                            'pedido_externo_id': order_id,
                            'item_externo_id': item_externo_id,
                            'sku_externo': sku_externo,
                            'quantidade_atendida': qty,
                            'created_at': datetime.utcnow().isoformat()
                        })
                    else:
                        logging.warning(f"Could not link External Item {sku_externo} (Ord: {order_id}) to any item in Demanda {demanda_id}")

            # 3. Batch Insert
            if records_to_insert:
                with get_db_session() as session:
                    for data in records_to_insert:
                        # Use model class to insert
                        record = DemandaItemOrigem(
                            demanda_item_id=data['demanda_item_id'],
                            plataforma=data['plataforma'],
                            pedido_externo_id=data['pedido_externo_id'],
                            item_externo_id=data['item_externo_id'],
                            sku_externo=data['sku_externo'],
                            quantidade_atendida=data['quantidade_atendida'],
                            created_at=datetime.fromisoformat(data['created_at'])
                        )
                        session.add(record)
                    session.commit()
                    
        except Exception as e:
            logging.error(f"Error registering processed items for Demanda {demanda_id}: {e}")
            raise

order_tracker_service = OrderTrackerService()

