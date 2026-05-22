from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


def parse_bool_strict(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def parse_int_safe(raw: Optional[str]) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def normalize_date_start(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT00:00:00")
    except ValueError:
        return None


def normalize_date_end(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT23:59:59.999")
    except ValueError:
        return None


def sanitize_search_term(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    for ch in [",", "(", ")", "{", "}", "[", "]"]:
        value = value.replace(ch, " ")
    value = value.replace("%", "").replace("*", " ")
    value = " ".join(value.split())
    return value or None


def parse_origin_key(origin_key: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not origin_key:
        return None, None
    text = str(origin_key).strip()
    if ":" not in text:
        return None, None

    origin_type, origin_value = text.split(":", 1)
    origin_type = origin_type.strip().lower()
    origin_value = origin_value.strip()
    if origin_type not in {"source", "canal", "marketplace", "bling_loja"} or not origin_value:
        return None, None
    return origin_type, origin_value


def resolve_order_ids_from_origin(
    supabase_db,
    origin_key: Optional[str],
) -> Tuple[Optional[Set[int]], Optional[str]]:
    origin_type, origin_value = parse_origin_key(origin_key)
    if not origin_type:
        return None, None

    if origin_type == "canal":
        canal_id = parse_int_safe(origin_value)
        if canal_id is None:
            return set(), origin_type
        rows = supabase_db.table("pedidos").select("id").eq("canal_venda_id", canal_id).execute().data or []
        return {row["id"] for row in rows if row.get("id") is not None}, origin_type

    if origin_type in {"source", "marketplace"}:
        marketplace_id = parse_int_safe(origin_value)
        if marketplace_id is None:
            return set(), origin_type
        rows = (
            supabase_db.table("pedidos")
            .select("id")
            .eq("marketplace_integration_id", marketplace_id)
            .execute()
            .data
            or []
        )
        return {row["id"] for row in rows if row.get("id") is not None}, origin_type

    # bling_loja:<id>
    loja_id = origin_value
    order_ids: Set[int] = set()

    # Path 1: explicit pedidos_bling link
    pedidos_bling_rows = supabase_db.table("pedidos_bling").select("id").eq("loja_id", loja_id).execute().data or []
    pedidos_bling_ids = [row.get("id") for row in pedidos_bling_rows if row.get("id") is not None]
    if pedidos_bling_ids:
        linked_rows = (
            supabase_db.table("pedidos")
            .select("id")
            .in_("pedido_bling_id", pedidos_bling_ids)
            .execute()
            .data
            or []
        )
        order_ids.update(row["id"] for row in linked_rows if row.get("id") is not None)

    # Path 2: direct denormalized field
    direct_rows = supabase_db.table("pedidos").select("id").eq("bling_loja_id", loja_id).execute().data or []
    order_ids.update(row["id"] for row in direct_rows if row.get("id") is not None)

    # Path 3: fallback through channel_connections mapping
    cc_rows = (
        supabase_db.table("channel_connections")
        .select("channel_id, marketplace_integration_id, bling_integration_id")
        .eq("is_active", True)
        .eq("aggregator_store_id", loja_id)
        .execute()
        .data
        or []
    )
    for cc in cc_rows:
        channel_id = cc.get("channel_id")
        marketplace_integration_id = cc.get("marketplace_integration_id")
        bling_integration_id = cc.get("bling_integration_id")

        if channel_id is not None:
            rows = supabase_db.table("pedidos").select("id").eq("canal_venda_id", channel_id).execute().data or []
            order_ids.update(row["id"] for row in rows if row.get("id") is not None)

        if marketplace_integration_id is not None:
            rows = (
                supabase_db.table("pedidos")
                .select("id")
                .eq("marketplace_integration_id", marketplace_integration_id)
                .execute()
                .data
                or []
            )
            order_ids.update(row["id"] for row in rows if row.get("id") is not None)

        if bling_integration_id is not None:
            rows = (
                supabase_db.table("pedidos")
                .select("id")
                .eq("bling_integration_id", bling_integration_id)
                .execute()
                .data
                or []
            )
            order_ids.update(row["id"] for row in rows if row.get("id") is not None)

    return order_ids, origin_type


def build_origin_options(supabase_db) -> List[Dict[str, Any]]:
    """Build canonical marketplace source options with live order counts."""
    order_rows = (
        supabase_db.table("pedidos")
        .select("id, marketplace_integration_id, bling_loja_id, pedido_bling_id")
        .execute()
        .data
        or []
    )
    if not order_rows:
        return []

    marketplace_ids = sorted(
        {row.get("marketplace_integration_id") for row in order_rows if row.get("marketplace_integration_id") is not None}
    )
    if not marketplace_ids:
        return []

    integration_rows = (
        supabase_db.table("installed_integrations")
        .select("id,instance_name,module_id")
        .in_("id", marketplace_ids)
        .execute()
        .data
        or []
    )
    module_ids = sorted({row.get("module_id") for row in integration_rows if row.get("module_id")})
    module_slug_map: Dict[str, str] = {}
    if module_ids:
        module_rows = (
            supabase_db.table("integration_modules")
            .select("id,slug")
            .in_("id", module_ids)
            .execute()
            .data
            or []
        )
        module_slug_map = {row["id"]: row.get("slug") for row in module_rows}

    integration_map: Dict[int, Dict[str, Optional[str]]] = {}
    for row in integration_rows:
        integration_map[row["id"]] = {
            "nome": row.get("instance_name") or f"Marketplace {row['id']}",
            "slug": module_slug_map.get(row.get("module_id")),
        }

    pb_ids = sorted({row.get("pedido_bling_id") for row in order_rows if row.get("pedido_bling_id") is not None})
    pb_store_map: Dict[int, str] = {}
    if pb_ids:
        pb_rows = (
            supabase_db.table("pedidos_bling").select("id,loja_id").in_("id", pb_ids).execute().data or []
        )
        pb_store_map = {row["id"]: str(row.get("loja_id")) for row in pb_rows if row.get("loja_id") is not None}

    totals_by_marketplace: Dict[int, int] = {}
    stores_by_marketplace: Dict[int, Set[str]] = {}
    for row in order_rows:
        marketplace_id = row.get("marketplace_integration_id")
        if marketplace_id is None:
            continue

        totals_by_marketplace[marketplace_id] = totals_by_marketplace.get(marketplace_id, 0) + 1
        store_id = row.get("bling_loja_id")
        if not store_id and row.get("pedido_bling_id") is not None:
            store_id = pb_store_map.get(row["pedido_bling_id"])
        if store_id:
            stores_by_marketplace.setdefault(marketplace_id, set()).add(str(store_id))

    color_by_slug = {
        "shopee": "#EE4D2D",
        "mercadolivre": "#FFF159",
        "amazon": "#FF9900",
        "shein": "#FF6B6B",
    }

    options: List[Dict[str, Any]] = []
    for marketplace_id in marketplace_ids:
        meta = integration_map.get(marketplace_id) or {}
        slug = meta.get("slug")
        options.append(
            {
                "key": f"source:{marketplace_id}",
                "legacy_key": f"marketplace:{marketplace_id}",
                "nome": meta.get("nome") or f"Marketplace {marketplace_id}",
                "tipo": "marketplace",
                "id": marketplace_id,
                "marketplace_integration_id": marketplace_id,
                "slug": slug,
                "color": color_by_slug.get(slug, "#007bff"),
                "lojas_bling": sorted(stores_by_marketplace.get(marketplace_id, set())),
                "total": totals_by_marketplace.get(marketplace_id, 0),
            }
        )

    return sorted(options, key=lambda item: (item.get("nome") or "").lower())
