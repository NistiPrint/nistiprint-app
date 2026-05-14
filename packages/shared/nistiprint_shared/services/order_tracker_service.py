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

    def filter_processed_orders(self, orders_list: List[Dict[str, Any]], platform: str) -> List[Dict[str, Any]]:
        """
        FILTRA PEDIDOS COMPLETOS JÁ PROCESSADOS, NÃO ITENS INDIVIDUAIS.
        
        Um pedido só é considerado processado se TODOS os seus itens estiverem
        vinculados a uma demanda via demandas_item_origem.
        
        REGRA DE NEGÓCIO: Pedidos são atômicos. Não existe "item A do pedido foi para 
        demanda 1, item B foi para demanda 2". Todos os itens de um pedido devem ser 
        consolidados na MESMA demanda.

        Args:
            orders_list: Lista de pedidos com estrutura:
                         {'pedido_externo_id': str, 'items': [{'sku_externo': str, 'quantidade': int}]}
            platform: Plataforma

        Returns:
            Lista de pedidos NÃO processados (com TODOS os itens originais).
            Se um pedido já foi totalmente consolidado, ele é excluído da lista.
        """
        if not orders_list:
            return []

        norm_platform = self.normalize_platform_name(platform)
        order_ids = [o.get('pedido_externo_id') for o in orders_list if o.get('pedido_externo_id')]

        if not order_ids:
            return orders_list

        try:
            # 1. Buscar TODOS os registros de origem para estes pedidos
            response = self.demandas_item_origem_table.select("*")\
                .eq('plataforma', norm_platform)\
                .in_('pedido_externo_id', order_ids)\
                .execute()

            existing_records = response.data or []

            # 2. Agrupar por pedido: {pedido_externo_id: [(sku, qty_atendida)]}
            processed_by_order = {}
            for record in existing_records:
                order_id = str(record['pedido_externo_id'])
                if order_id not in processed_by_order:
                    processed_by_order[order_id] = []
                processed_by_order[order_id].append({
                    'sku_externo': str(record.get('sku_externo')),
                    'quantidade_atendida': int(record['quantidade_atendida'])
                })

            # 3. Filtrar pedidos: manter apenas os NÃO totalmente processados
            orders_to_process = []
            
            for order in orders_list:
                order_id = str(order.get('pedido_externo_id', ''))
                order_items = order.get('items', [])
                
                # Pedido sem itens? Ignorar
                if not order_items:
                    continue
                
                processed_items = processed_by_order.get(order_id, [])
                
                # 4. Verificar se TODOS os itens do pedido estão processados
                #    com a quantidade correta
                all_items_processed = True
                
                for order_item in order_items:
                    sku = str(order_item.get('sku_externo') or order_item.get('sku'))
                    qty_requested = int(order_item.get('quantidade', 1))
                    
                    # Buscar quantidade processada para este SKU
                    qty_processed = sum(
                        p['quantidade_atendida'] 
                        for p in processed_items 
                        if p['sku_externo'] == sku
                    )
                    
                    # Se quantidade processada < quantidade do pedido, item NÃO processado
                    if qty_processed < qty_requested:
                        all_items_processed = False
                        break
                
                # 5. Se NEM todos os itens estão processados, incluir pedido na lista
                #    (com TODOS os itens originais, não parcial)
                if not all_items_processed:
                    orders_to_process.append(order)

            return orders_to_process

        except Exception as e:
            logging.error(f"Error filtering processed orders: {e}", exc_info=True)
            # Fail-safe: retorna lista original (pode causar duplicação, mas não perde dados)
            return orders_list

    # ✅ LEGACY: Mantido para compatibilidade, mas redireciona para novo método
    def filter_processed_items(self, orders_list: List[Dict[str, Any]], platform: str) -> List[Dict[str, Any]]:
        """
        Método legado - redireciona para filter_processed_orders().
        Será removido em futura versão.
        """
        return self.filter_processed_orders(orders_list, platform)

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
        Registra vínculo entre pedidos consolidados e itens da demanda.
        
        REGRA DE NEGÓCIO: Todos os itens de UM PEDIDO devem ser vinculados à MESMA demanda.
        Este método registra a rastreabilidade de qual pedido originou qual quantidade na demanda.

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

            # ✅ VALIDAÇÃO DE CONSISTÊNCIA: Coletar demanda_item_ids por pedido
            # para garantir que todos os itens de um pedido vão para a mesma demanda
            pedido_demanda_items = {}  # {order_id: set of demanda_item_ids}

            records_to_insert = []

            for order in orders_list:
                order_id = str(order.get('pedido_externo_id', ''))
                
                if order_id not in pedido_demanda_items:
                    pedido_demanda_items[order_id] = set()

                for item in order.get('items', []):
                    sku_externo = str(item.get('sku_externo') or item.get('sku') or '').strip()
                    item_externo_id = str(item.get('item_externo_id') or '')
                    qty = int(item.get('quantidade', 0))
                    product_id = str(item.get('produto_id') or '') # Internal resolved ID

                    if qty <= 0:
                        continue

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
                        # ✅ Rastrear qual demanda_item este pedido está usando
                        pedido_demanda_items[order_id].add(target_demanda_item_id)
                        
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

            # ✅ VALIDAÇÃO DE CONSISTÊNCIA: Verificar se algum pedido tem itens em múltiplos demanda_items
            # Isso não é um erro - é esperado que um pedido com itens diferentes vá para demanda_items diferentes
            # O importante é que todos os itens do pedido estão nesta MESMA demanda (demanda_id)
            for order_id, item_ids in pedido_demanda_items.items():
                if item_ids:
                    logging.info(f"Pedido {order_id} vinculado a {len(item_ids)} item(s) da Demanda {demanda_id}")

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

            logging.info(f"Registrados {len(records_to_insert)} vínculos de origem para Demanda {demanda_id}")

        except Exception as e:
            logging.error(f"Error registering processed items for Demanda {demanda_id}: {e}", exc_info=True)
            raise

order_tracker_service = OrderTrackerService()

