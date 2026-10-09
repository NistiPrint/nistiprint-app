import json

from sqlalchemy import text

from nistiprint_shared.database.database import db
from nistiprint_shared.models.bling_pedido_itens import BlingPedidoItens
from nistiprint_shared.models.bling_pedidos import BlingPedidos
from nistiprint_shared.models.shopee_orders import ShopeeOrders
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

        if mode == "legacy":
            return self.get_personalized_orders_legacy()

        return self.get_personalized_orders_v2()

    def get_personalized_orders_v2(self):
        """
        Retrieves personalized orders using the optimized service-layer assembly.
        Returns a list of processed order dictionaries.
        """
        try:
            from nistiprint_shared.services.ai_personalization_service import get_orders_with_chats

            rows = get_orders_with_chats()

            processed_orders = []
            for row in rows:
                contato = self._parse_json_field(row.get("contato"), default={}) or {}
                itens = [self._normalize_item(item) for item in (row.get("items") or row.get("itens") or [])]

                if not contato.get("nome"):
                    nome_cliente = row.get("nome_cliente", "") or ""
                    if nome_cliente:
                        contato["nome"] = nome_cliente

                processed_orders.append({
                    "id": row["id"],
                    "numero": row.get("order_id") or row.get("numero_pedido"),
                    "nome_cliente": row.get("nome_cliente", "") or "",
                    "numeroLoja": row.get("shopee_order_sn") or row.get("numero_loja"),
                    "marketplace_integration_id": row.get("marketplace_integration_id"),
                    "data": row.get("order_date") or row.get("data_pedido"),
                    "contato": contato,
                    "itens": itens,
                    "shopee": {
                        "username": row.get("buyer_username") or "",
                        "order_sn": row.get("shopee_order_sn") or row.get("numero_loja"),
                        "message": (
                            row.get("latest_buyer_message")
                            or row.get("message_to_seller")
                            or row.get("shopee_message")
                        ),
                        "message_to_seller": row.get("message_to_seller") or row.get("shopee_message"),
                        "latest_buyer_message": row.get("latest_buyer_message") or "",
                    },
                    "personalizado": row.get("personalizado", True),
                    "has_chat_messages": row.get("has_chat_messages", False),
                    "has_buyer_message": row.get("has_buyer_message", False),
                    "deletado": row.get("deletado", False),
                    "last_ai_executed_at": row.get("last_ai_executed_at"),
                    "last_buyer_message_at": row.get("last_buyer_message_at"),
                    "last_chat_message_at": row.get("last_chat_message_at"),
                    "needs_ai_processing": row.get("needs_ai_processing", False),
                    "ai_status": row.get("ai_status"),
                    "chat_context_ambiguous": row.get("chat_context_ambiguous", False),
                })

            return processed_orders
        except Exception as e:
            print(f"Error executing view-based personalized orders query: {e}")
            import traceback
            traceback.print_exc()
            raise e

    def get_personalized_orders_page(self, *, page=1, page_size=20, search="",
                                    ai_filter="", chat_filter="",
                                    integration_id=None, include_unassigned=False):
        """Filter and count through the summary view, then assemble one page."""
        from nistiprint_shared.database.supabase_db_service import supabase_db
        page = max(1, int(page))
        page_size = min(100, max(1, int(page_size)))
        summary_table = "view_shopee_personalization_order_summary"

        def scoped(query):
            if integration_id is None:
                return query
            if include_unassigned:
                return query.or_(
                    f"marketplace_integration_id.eq.{int(integration_id)},marketplace_integration_id.is.null"
                )
            return query.eq("marketplace_integration_id", int(integration_id))

        def count_for(**filters):
            query = scoped(supabase_db.table(summary_table).select("id", count="exact", head=True))
            for column, value in filters.items():
                query = query.eq(column, value)
            return int(getattr(query.execute(), "count", 0) or 0)

        status_counts = {
            "pendente_ia": count_for(needs_ai_processing=True),
            "com_chat": count_for(has_chat_messages=True),
            "sem_chat": count_for(has_chat_messages=False),
            "nome_identificado": count_for(has_identified_name=True),
            "sem_nome": count_for(has_no_name=True),
        }
        query = scoped(supabase_db.table(summary_table).select("id", count="exact"))
        filters = {
            "pendente_ia": ("needs_ai_processing", True),
            "nome_identificado": ("has_identified_name", True),
            "sem_nome": ("has_no_name", True),
            "com_chat": ("has_chat_messages", True),
            "sem_chat": ("has_chat_messages", False),
        }
        for selected_filter in (ai_filter, chat_filter):
            if selected_filter in filters:
                column, value = filters[selected_filter]
                query = query.eq(column, value)
        if search.strip():
            value = search.strip().replace("%", "\\%").replace(",", "\\,")
            query = query.or_(
                f"numero_pedido.ilike.%{value}%,numero_loja.ilike.%{value}%,"
                f"nome_cliente.ilike.%{value}%,buyer_username.ilike.%{value}%"
            )
        response = query.order("data_pedido", desc=True).order("id", desc=True).range(
            (page - 1) * page_size, page * page_size - 1
        ).execute()
        ids = [row["id"] for row in response.data or []]
        rows = (supabase_db.table("view_vendas_personalizadas_v3").select("*")
                .in_("id", ids).execute().data or []) if ids else []
        rows_by_id = {int(row["id"]): row for row in rows}
        orders = []
        for order_id in ids:
            row = rows_by_id.get(int(order_id))
            if not row:
                continue
            contato = self._parse_json_field(row.get("contato"), default={}) or {}
            if not contato.get("nome"):
                contato["nome"] = row.get("nome_cliente") or ""
            items = [self._normalize_item(item) for item in self._parse_json_field(row.get("itens"), default=[])]
            orders.append({
                "id": row["id"], "numero": row.get("numero_pedido"),
                "numeroLoja": row.get("numero_loja"), "nome_cliente": row.get("nome_cliente") or "",
                "data": row.get("data_pedido"), "contato": contato, "itens": items,
                "shopee": {"username": row.get("buyer_username") or "",
                           "order_sn": row.get("numero_loja"),
                           "message": row.get("shopee_message") or ""},
                "personalizado": True, "has_chat_messages": bool(row.get("has_chat_messages")),
                "deletado": bool(row.get("deletado")),
                "last_ai_executed_at": row.get("last_ai_executed_at"),
                "last_buyer_message_at": row.get("last_buyer_message_at"),
                "needs_ai_processing": bool(row.get("needs_ai_processing")),
                "ai_status": row.get("ai_status"),
                "marketplace_integration_id": row.get("marketplace_integration_id"),
            })
        total = int(getattr(response, "count", 0) or 0)
        return {
            "bling_orders": orders,
            "pagination": {"page": page, "page_size": page_size, "total": total,
                           "has_next": page * page_size < total},
            "status_counts": status_counts,
        }

    @staticmethod
    def _parse_json_field(value, default):
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return default
        return default

    def _normalize_item(self, item):
        item = item or {}
        normalized_item = dict(item)
        personalizations = self._parse_json_field(normalized_item.get("personalizations"), default=[])
        normalized_personalizations = []

        for personalization in personalizations:
            if not personalization:
                continue
            normalized_personalization = dict(personalization)
            detalhes = self._parse_json_field(normalized_personalization.get("detalhes_personalizacao"), default={}) or {}
            metadata = self._parse_json_field(normalized_personalization.get("metadata"), default={}) or {}

            normalized_personalization["nome"] = normalized_personalization.get("customization_name")
            normalized_personalization["quantity_to_personalize"] = (
                normalized_personalization.get("quantity_to_personalize")
                or detalhes.get("quantity_to_personalize")
                or metadata.get("quantity_to_personalize")
                or 1
            )
            normalized_personalization["initial_source_message_id"] = (
                normalized_personalization.get("initial_source_message_id")
                or detalhes.get("initial_source_message_id")
                or metadata.get("initial_source_message_id")
            )
            normalized_personalizations.append(normalized_personalization)

        normalized_item["personalizations"] = normalized_personalizations
        return normalized_item

    def get_personalized_orders_legacy(self):
        """
        Retrieves personalized orders directly from the Legacy MySQL database using view.
        """
        try:
            from nistiprint_shared.services.legacy_sync_service import LegacySyncService
            conn = LegacySyncService._get_legacy_connection()

            with conn:
                query = text("""
                    SELECT * FROM view_vendas_personalizadas
                    WHERE personalizado = 1 AND deletado = 0
                    ORDER BY data_pedido DESC
                """)

                result = conn.execute(query).mappings().all()
                rows = [dict(row) for row in result]

                processed_orders = []
                for row in rows:
                    order_items = row["itens"]
                    if isinstance(order_items, str):
                        try:
                            order_items = json.loads(order_items)
                        except Exception:
                            order_items = []

                    for item in order_items:
                        item["quantidade"] = float(item.get("quantidade", 0))
                        item["valor"] = float(item.get("valor", 0))

                    processed_orders.append({
                        "id": row["id"],
                        "numero": row["numero_pedido"],
                        "numeroLoja": row["numero_loja"],
                        "data": row["data_pedido"].isoformat() if hasattr(row["data_pedido"], "isoformat") else str(row["data_pedido"]),
                        "contato": json.loads(row["contato"]) if isinstance(row["contato"], str) else (row["contato"] or {}),
                        "itens": order_items,
                        "shopee": {
                            "username": row["buyer_username"] or "",
                            "order_sn": row["numero_lo_ja"] if "numero_lo_ja" in row else row["numero_loja"],
                            "message": row["shopee_message"],
                        },
                        "personalizado": bool(row["personalizado"]),
                        "has_chat_messages": bool(row["has_chat_messages"]),
                        "deletado": bool(row["deletado"]),
                        "totalProdutos": sum(item["valor"] * item["quantidade"] for item in order_items),
                    })

                return processed_orders

        except Exception as e:
            print(f"Error executing legacy personalized orders query via view: {e}")
            import traceback
            traceback.print_exc()
            raise e


orders_query_service = OrdersQueryService()
