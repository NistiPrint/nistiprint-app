import json
from sqlalchemy import text
from nistiprint_shared.database.database import db
# from nistiprint_shared.models.v2_chat_events import V2ChatEvents # Deprecated for Supabase session
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.models.shopee_orders import ShopeeOrders
# from nistiprint_shared.models.order_personalizations import OrderPersonalizations # Deprecated for Supabase session
from nistiprint_shared.models.supabase_chat import MensagemChatShopee
from nistiprint_shared.models.supabase_personalizacao import PersonalizacaoPedido

from nistiprint_shared.database.supabase_db_service import get_db_session as get_supabase_session

class OrdersQueryService:
    """
    Service responsible for complex order queries, specifically aggregating data
    from Bling, Shopee, and Personalizations.
    """

    def get_personalized_orders(self, mode=None):
        """
        Retrieves personalized orders based on app configuration (V2 or Legacy).
        """
        if not mode:
            from nistiprint_shared.services.app_config_service import app_config_service
            mode = app_config_service.get_operational_mode()
        
        if mode == 'legacy':
            return self.get_personalized_orders_legacy()
        
        return self.get_personalized_orders_v2()

    def get_personalized_orders_v2(self):
        """
        Retrieves personalized orders using a PostgreSQL View for maximum performance.
        Returns a list of processed order dictionaries.
        """
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db
            from datetime import datetime, timedelta

            # Calculate date 5 days ago
            five_days_ago = (datetime.now() - timedelta(days=5)).isoformat()

            # Use Supabase client to query the NEW view V3
            # Order by numero_loja (Bling number) descending to match orders screen
            # Filter orders from last 5 days
            response = supabase_db.table('view_vendas_personalizadas_v3') \
                .select('*') \
                .order('numero_loja', desc=True) \
                .gte('data_pedido', five_days_ago) \
                .execute()
            
            rows = response.data if response.data else []
            
            # Map view fields back to the format expected by the frontend
            processed_orders = []
            for row in rows:
                contato = row.get('contato')
                if isinstance(contato, str):
                    try:
                        contato = json.loads(contato)
                    except Exception:
                        contato = {}

                processed_orders.append({
                    'id': row['id'],
                    'numero': row['numero_pedido'],
                    'nome_cliente': row.get('nome_cliente', '') or '',
                    'numeroLoja': row['numero_loja'],
                    'data': row['data_pedido'],
                    'contato': contato,
                    'itens': row['itens'] if row['itens'] else [],
                    'shopee': {
                        'username': row.get('buyer_username') or '',
                        'order_sn': row['numero_loja'],
                        'message': row.get('shopee_message')
                    },
                    'personalizado': row.get('personalizado', True),
                    'has_chat_messages': row.get('has_chat_messages', False),
                    'deletado': row.get('deletado', False)
                })

            return processed_orders
        except Exception as e:
            print(f"Error executing view-based personalized orders query: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def get_personalized_orders_legacy(self):
        """
        Retrieves personalized orders directly from the Legacy MySQL database using view.
        """
        try:
            from nistiprint_shared.services.legacy_sync_service import LegacySyncService
            conn = LegacySyncService._get_legacy_connection()
            
            with conn:
                # Use the new MySQL View for maximum performance
                query = text("""
                    SELECT * FROM view_vendas_personalizadas 
                    WHERE personalizado = 1 AND deletado = 0
                    ORDER BY data_pedido DESC
                """)
                
                result = conn.execute(query).mappings().all()
                rows = [dict(row) for row in result]
                
                processed_orders = []
                for row in rows:
                    # In MySQL view, 'itens' comes as a JSON string
                    order_items = row['itens']
                    if isinstance(order_items, str):
                        try:
                            order_items = json.loads(order_items)
                        except:
                            order_items = []
                    
                    # Ensure numeric fields are floats
                    for item in order_items:
                        item['quantidade'] = float(item.get('quantidade', 0))
                        item['valor'] = float(item.get('valor', 0))

                    processed_orders.append({
                        'id': row['id'],
                        'numero': row['numero_pedido'],
                        'numeroLoja': row['numero_loja'],
                        'data': row['data_pedido'].isoformat() if hasattr(row['data_pedido'], 'isoformat') else str(row['data_pedido']),
                        'contato': json.loads(row['contato']) if isinstance(row['contato'], str) else (row['contato'] or {}),
                        'itens': order_items,
                        'shopee': {
                            'username': row['buyer_username'] or '',
                            'order_sn': row['numero_lo_ja'] if 'numero_lo_ja' in row else row['numero_loja'],
                            'message': row['shopee_message']
                        },
                        'personalizado': bool(row['personalizado']),
                        'has_chat_messages': bool(row['has_chat_messages']),
                        'deletado': bool(row['deletado']),
                        'totalProdutos': sum(item['valor'] * item['quantidade'] for item in order_items)
                    })
                
                return processed_orders

        except Exception as e:
            print(f"Error executing legacy personalized orders query via view: {e}")
            import traceback
            traceback.print_exc()
            raise e

orders_query_service = OrdersQueryService()

