from __future__ import annotations

import logging
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _compact(val) for key, val in value.items() if val not in (None, "", [], {})}
    if isinstance(value, list):
        return [_compact(item) for item in value if item not in (None, "", [], {})]
    return value


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default


class CanonicalOrderSnapshotService:
    """Persists display-ready order data independent from the ingest source."""

    def upsert_snapshot(
        self,
        *,
        pedido_id: int | None,
        ingest_source: str,
        marketplace: str | None,
        marketplace_order_id: str | None,
        marketplace_integration_id: int | None,
        bling_integration_id: int | None = None,
        bling_order_id: Any = None,
        bling_order_number: Any = None,
        customer: dict | None = None,
        items: list[dict] | None = None,
        logistics: dict | None = None,
        financial: dict | None = None,
        platform_fields: dict | None = None,
        raw_refs: dict | None = None,
        upsert_items: bool = False,
    ) -> dict:
        if not pedido_id:
            return {"success": False, "error": "pedido_id ausente"}

        items = items or []
        customer = customer or {}
        logistics = logistics or {}
        financial = financial or {}
        platform_fields = platform_fields or {}
        raw_refs = raw_refs or {}

        identity = _compact({
            "ingest_source": ingest_source,
            "marketplace": marketplace,
            "marketplace_order_id": str(marketplace_order_id) if marketplace_order_id is not None else None,
            "marketplace_integration_id": marketplace_integration_id,
            "bling_integration_id": bling_integration_id,
            "bling_order_id": bling_order_id,
            "bling_order_number": str(bling_order_number) if bling_order_number is not None else None,
        })
        now = get_now_iso()

        snapshot = {
            "pedido_id": pedido_id,
            "identity": identity,
            "customer": _compact(customer),
            "items": _compact(items),
            "logistics": _compact(logistics),
            "financial": _compact(financial),
            "platform_fields": _compact(platform_fields),
            "raw_refs": _compact(raw_refs),
            "source_history": [{
                "source": ingest_source,
                "marketplace": marketplace,
                "at": now,
            }],
            "updated_at": now,
        }

        existing = (
            supabase_db.table("pedido_snapshots")
            .select("id,source_history")
            .eq("pedido_id", pedido_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if existing:
            history = existing[0].get("source_history") or []
            if not isinstance(history, list):
                history = []
            snapshot["source_history"] = history[-19:] + snapshot["source_history"]
            supabase_db.table("pedido_snapshots").update(snapshot).eq("pedido_id", pedido_id).execute()
        else:
            snapshot["created_at"] = now
            supabase_db.table("pedido_snapshots").insert(snapshot).execute()

        self._update_pedido_compat(
            pedido_id=pedido_id,
            identity=identity,
            customer=customer,
            logistics=logistics,
            financial=financial,
            platform_fields=platform_fields,
        )
        if upsert_items:
            self._replace_items(pedido_id, items)

        return {"success": True, "pedido_id": pedido_id}

    def _update_pedido_compat(
        self,
        *,
        pedido_id: int,
        identity: dict,
        customer: dict,
        logistics: dict,
        financial: dict,
        platform_fields: dict,
    ) -> None:
        update = {
            "marketplace_order_id": identity.get("marketplace_order_id"),
            "bling_order_id": identity.get("bling_order_id"),
            "bling_order_number": identity.get("bling_order_number"),
            "ingest_source": identity.get("ingest_source"),
            "buyer_username": platform_fields.get("buyer_username") or customer.get("username") or customer.get("nickname"),
            "shipping_carrier": logistics.get("shipping_carrier") or platform_fields.get("shipping_carrier"),
            "message_to_seller": platform_fields.get("message_to_seller"),
            "cliente_nome": customer.get("name") or customer.get("nome") or customer.get("username") or customer.get("nickname"),
            "cliente_documento": customer.get("document") or customer.get("documento") or customer.get("numeroDocumento"),
            "cliente_telefone": customer.get("phone") or customer.get("telefone"),
            "cliente_email": customer.get("email"),
            "informacoes_cliente": _compact(customer) or None,
            "total_pedido": financial.get("total"),
            "moeda": financial.get("currency"),
            "data_limite_envio": logistics.get("deadline") or logistics.get("ship_by_date") or logistics.get("expected_date"),
            "data_compra_marketplace": logistics.get("purchase_at"),
            "data_pagamento_marketplace": logistics.get("payment_at"),
            "data_coleta": logistics.get("collection_at"),
            "data_envio_marketplace": logistics.get("marketplace_shipped_at"),
            "regra_logistica_integracao_id": logistics.get("rule_id"),
            "servico_logistico": logistics.get("service") or logistics.get("servico_logistico"),
            "is_flex": logistics.get("is_flex"),
            "is_fulfillment": logistics.get("is_fulfillment"),
            "updated_at": get_now_iso(),
        }
        update = {key: value for key, value in update.items() if value is not None}
        if update:
            supabase_db.table("pedidos").update(update).eq("id", pedido_id).execute()

    def _replace_items(self, pedido_id: int, items: list[dict]) -> None:
        if not items:
            return
        pedido_rows = (
            supabase_db.table("pedidos")
            .select("pedido_bling_id")
            .eq("id", pedido_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if pedido_rows and pedido_rows[0].get("pedido_bling_id"):
            logger.info(
                "[snapshot] skipping item replacement for pedido_id=%s because pedido_bling_id exists",
                pedido_id,
            )
            return
        supabase_db.table("itens_pedido").delete().eq("pedido_id", pedido_id).execute()
        rows = []
        for item in items:
            quantity = _safe_float(item.get("quantity") or item.get("quantidade"), 1.0)
            unit_price = _safe_float(item.get("unit_price") or item.get("preco_unitario") or item.get("price"))
            rows.append({
                "pedido_id": pedido_id,
                "sku_externo": item.get("sku") or item.get("sku_externo"),
                "descricao": item.get("name") or item.get("descricao"),
                "quantidade": quantity,
                "preco_unitario": unit_price,
                "subtotal": _safe_float(item.get("subtotal"), unit_price * quantity),
                "updated_at": get_now_iso(),
            })
        if rows:
            supabase_db.table("itens_pedido").insert(rows).execute()


canonical_order_snapshot_service = CanonicalOrderSnapshotService()
