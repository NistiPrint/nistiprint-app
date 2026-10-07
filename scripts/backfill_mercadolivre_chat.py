"""Recover legacy Mercado Livre chat order links, dates, and attachments.

Run from the repository root with the project virtual environment:
    .venv/Scripts/python scripts/backfill_mercadolivre_chat.py --dry-run
    .venv/Scripts/python scripts/backfill_mercadolivre_chat.py --apply
    .venv/Scripts/python scripts/backfill_mercadolivre_chat.py --dry-run --integration-id 7091

Dry-run is the default. Applying is idempotent and updates only the affected fields.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "packages" / "shared"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)


def _order_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("ID de pedido desconhecido")
    result = str(value).strip()
    if not result or len(result) > 160:
        raise ValueError("ID de pedido vazio ou extenso demais")
    return result


def _legacy_value(value: str) -> Any:
    if len(value) > 1000:
        raise ValueError("valor legado extenso demais")
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _conversation_order_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("order_ids não é uma lista")
    order_ids = []
    for entry in value:
        parsed = _legacy_value(entry) if isinstance(entry, str) else entry
        order_ids.append(_order_id(parsed))
    return list(dict.fromkeys(order_ids))


def _message_timestamp(raw: dict) -> str | None:
    dates = raw.get("message_date")
    value = (dates.get("created") if isinstance(dates, dict) else None)
    value = value or raw.get("date_created") or raw.get("date")
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _raw_json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _read_all(query: Any, page_size: int = 500) -> list[dict]:
    rows = []
    start = 0
    while True:
        page = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def run(*, apply: bool, integration_id: int | None) -> dict:
    _load_env()
    from nistiprint_shared.database.supabase_db_service import supabase_db

    conversations_query = supabase_db.table("mercadolivre_chat_conversations").select(
        "id,marketplace_integration_id,pack_id,order_ids,last_message_at"
    )
    orders_query = supabase_db.table("pedidos").select(
        "marketplace_integration_id,marketplace_order_id,codigo_pedido_externo"
    )
    messages_query = supabase_db.table("mercadolivre_chat_messages").select(
        "marketplace_integration_id,pack_id,provider_message_id,created_at,attachments,raw_json"
    )
    if integration_id is not None:
        conversations_query = conversations_query.eq("marketplace_integration_id", integration_id)
        orders_query = orders_query.eq("marketplace_integration_id", integration_id)
        messages_query = messages_query.eq("marketplace_integration_id", integration_id)
    conversations = _read_all(conversations_query)
    orders = _read_all(orders_query)
    messages = _read_all(messages_query)

    known_orders: dict[int, set[str]] = {}
    for order in orders:
        account = int(order["marketplace_integration_id"])
        identifiers = known_orders.setdefault(account, set())
        identifiers.update(str(order[key]).strip() for key in
                           ("marketplace_order_id", "codigo_pedido_externo")
                           if order.get(key) not in (None, ""))

    conversation_updates = []
    unresolved = []
    for conversation in conversations:
        account = int(conversation["marketplace_integration_id"])
        try:
            normalized = _conversation_order_ids(conversation.get("order_ids"))
            if not set(normalized).issubset(known_orders.get(account, set())):
                raise ValueError("pedido não encontrado na mesma integração")
        except (TypeError, ValueError, KeyError) as exc:
            unresolved.append({"conversation_id": conversation.get("id"), "reason": str(exc)})
            continue
        changes = {}
        if conversation.get("order_ids") != normalized:
            changes["order_ids"] = normalized
        if changes:
            conversation_updates.append({**conversation, "changes": changes})

    message_updates = []
    latest_by_pack: dict[tuple[int, str], str] = {}
    for message in messages:
        key = (int(message["marketplace_integration_id"]), str(message["pack_id"]))
        raw = _raw_json(message.get("raw_json"))
        timestamp = _message_timestamp(raw)
        attachments = raw.get("message_attachments")
        if not isinstance(attachments, list):
            attachments = raw.get("attachments")
        changes = {}
        if not message.get("created_at") and timestamp:
            changes["created_at"] = timestamp
        if not message.get("attachments") and isinstance(attachments, list) and attachments:
            changes["attachments"] = attachments
        if timestamp and (key not in latest_by_pack or timestamp > latest_by_pack[key]):
            latest_by_pack[key] = timestamp
        if changes:
            message_updates.append({**message, "changes": changes})

    for conversation in conversations:
        key = (int(conversation["marketplace_integration_id"]), str(conversation["pack_id"]))
        latest = latest_by_pack.get(key)
        if latest and conversation.get("last_message_at") != latest:
            existing = next((row for row in conversation_updates if row["id"] == conversation["id"]), None)
            if existing:
                existing["changes"]["last_message_at"] = latest
            else:
                conversation_updates.append({**conversation, "changes": {"last_message_at": latest}})

    if apply:
        for message in message_updates:
            (supabase_db.table("mercadolivre_chat_messages").update(message["changes"])
             .eq("marketplace_integration_id", message["marketplace_integration_id"])
             .eq("provider_message_id", message["provider_message_id"]).execute())
        for conversation in conversation_updates:
            (supabase_db.table("mercadolivre_chat_conversations").update(conversation["changes"])
             .eq("marketplace_integration_id", conversation["marketplace_integration_id"])
             .eq("id", conversation["id"]).execute())

    return {
        "mode": "apply" if apply else "dry-run",
        "integration_id": integration_id,
        "conversations_scanned": len(conversations),
        "conversations_to_update": len(conversation_updates),
        "messages_scanned": len(messages),
        "messages_to_update": len(message_updates),
        "messages_with_dates_recovered": sum("created_at" in row["changes"] for row in message_updates),
        "unresolved_conversations": unresolved,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="somente relata alterações (padrão)")
    mode.add_argument("--apply", action="store_true", help="grava alterações validadas no Supabase")
    parser.add_argument("--integration-id", type=int, help="limita a uma conta Mercado Livre")
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, integration_id=args.integration_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
