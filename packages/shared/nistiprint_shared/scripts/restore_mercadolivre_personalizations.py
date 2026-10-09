"""Preview or restore Mercado Livre names erased by item resynchronization.

Run without --apply for a read-only report. Apply only after migrations 13:00
and 14:00 have been deployed.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.mercadolivre_personalization_service import (
    _context_hash,
    _json,
    _text,
)


def _message_fingerprint(rows: list[dict]) -> list[dict]:
    return [{"id": str(row.get("provider_message_id") or row.get("id") or ""),
             "sender_role": row.get("sender_role"), "created_at": row.get("created_at"),
             "text": row.get("text_content") if "text_content" in row else row.get("text"),
             "attachments": row.get("attachments") or []}
            for row in sorted(rows, key=lambda value: (str(value.get("created_at") or ""),
                                                       str(value.get("provider_message_id") or "")))]


def _validate_log(log: dict, conversation: dict, messages: list[dict],
                  orders: list[dict], items: list[dict]) -> tuple[list[dict], str | None]:
    source = _json(log.get("input_data"))
    result = _json(log.get("model_result"))
    if not isinstance(source, dict) or not isinstance(result, dict):
        return [], "log sem entrada ou resultado JSON recuperável"
    if result.get("status") != "SUCCESS" or log.get("status") != "success":
        return [], "execução mais recente não teve sucesso inequívoco"
    old_messages = source.get("messages")
    entries = result.get("personalized_items")
    if not isinstance(old_messages, list) or not isinstance(entries, list):
        return [], "mensagens ou itens do log em formato inválido"
    if _message_fingerprint(old_messages) != _message_fingerprint(messages):
        return [], "conversa mudou após a execução registrada"
    digest = _context_hash(messages)
    if conversation.get("context_hash") != digest:
        return [], "hash da conversa não corresponde ao contexto atual"

    current_orders = {str(order.get("marketplace_order_id") or order.get("codigo_pedido_externo")): order
                      for order in orders}
    current_items: dict[int, list[dict]] = defaultdict(list)
    for item in items:
        current_items[int(item["pedido_id"])].append(item)
    old_orders = {str(order.get("external_order_id")): order for order in source.get("orders", [])}
    order_id_by_external = {}
    for external_id, old_order in old_orders.items():
        current = current_orders.get(external_id)
        if not current:
            return [], f"pedido {external_id} não está mais associado à conta"
        if _text(old_order.get("message_to_seller")) != _text(current.get("message_to_seller")):
            return [], f"mensagem ao vendedor do pedido {external_id} mudou"
        order_id_by_external[external_id] = int(current["id"])

    messages_by_id = {str(message.get("provider_message_id")): message for message in messages
                      if message.get("sender_role") == "buyer"}
    records = []
    allocated: dict[int, int] = defaultdict(int)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return [], "linha de resultado não é um objeto"
        try:
            old_item_id = int(entry.get("item_id"))
            quantity = int(entry.get("quantity_to_personalize"))
        except (TypeError, ValueError):
            return [], "ID ou quantidade do resultado inválido"
        old_order = next((row for row in old_orders.values()
                          if any(str(item.get("item_id")) == str(old_item_id)
                                 for item in row.get("items", []))), None)
        old_item = next((item for item in (old_order or {}).get("items", [])
                         if str(item.get("item_id")) == str(old_item_id)), None)
        if old_order is None or old_item is None:
            return [], f"item antigo {old_item_id} não existe na entrada registrada"
        external_id = str(old_order.get("external_order_id"))
        order_id = order_id_by_external[external_id]
        description = _text(old_item.get("description"))
        old_quantity = int(old_item.get("quantity") or 1)
        candidates = [item for item in current_items[order_id]
                      if _text(item.get("titulo_anuncio") or item.get("descricao")) == description
                      and int(item.get("quantidade") or 1) == old_quantity]
        direct = [item for item in candidates if int(item["id"]) == old_item_id]
        candidates = direct or candidates
        if len(candidates) != 1:
            return [], f"item {description!r} no pedido {external_id} tem correspondência ambígua"
        item = candidates[0]
        name = _text(entry.get("customization_name")) or None
        initial = _text(entry.get("customization_initial")) or None
        name_source = entry.get("name_source_message_id")
        initial_source = entry.get("initial_source_message_id")
        if name and (name_source != "message_to_seller"
                     and (str(name_source) not in messages_by_id or not name_source)):
            return [], f"fonte da personalização {name!r} não existe na conversa atual"
        if initial and (initial_source != "message_to_seller"
                        and (str(initial_source) not in messages_by_id or not initial_source)):
            return [], f"fonte da inicial {initial!r} não existe na conversa atual"
        if name_source == "message_to_seller" and not _text(old_order.get("message_to_seller")):
            return [], "mensagem ao vendedor indicada como fonte não existe"
        if initial_source == "message_to_seller" and not _text(old_order.get("message_to_seller")):
            return [], "mensagem ao vendedor indicada como fonte não existe"
        if quantity < 1 or quantity > int(item.get("quantidade") or 1):
            return [], "quantidade extraída incompatível com o item atual"
        allocated[int(item["id"])] += quantity
        if allocated[int(item["id"])] > int(item.get("quantidade") or 1):
            return [], "soma das quantidades extraídas excede a quantidade atual"
        if name or initial:
            records.append({
                "pedido_id": order_id, "item_pedido_id": int(item["id"]),
                "provider_order_id": external_id,
                "provider_item_id": f"restored-log-{log['id']}-row-{index}",
                "provider_message_id": name_source or initial_source,
                "quantity_to_personalize": quantity,
                "customization_name": name, "customization_initial": initial,
                "reasoning": _text(result.get("reasoning"))[:1500],
                "details": {"name_source_message_id": name_source,
                            "initial_source_message_id": initial_source},
            })
    if not records:
        return [], "execução não contém nomes ou iniciais para restaurar"
    return records, None


def run(*, integration_id: int | None = None, apply: bool = False) -> dict:
    query = supabase_db.table("mercadolivre_personalization_logs").select("*").eq("status", "success")
    if integration_id is not None:
        query = query.eq("marketplace_integration_id", int(integration_id))
    logs = query.order("executed_at", desc=True).execute().data or []
    latest: dict[tuple[int, str], dict] = {}
    for log in logs:
        if not log.get("pack_id") or not isinstance(_json(log.get("model_result")), dict):
            continue
        key = (int(log["marketplace_integration_id"]), str(log["pack_id"]))
        latest.setdefault(key, log)

    report = {"mode": "apply" if apply else "dry_run", "eligible": [], "restored": [], "pending": []}
    for (account_id, pack_id), log in latest.items():
        result = _json(log.get("model_result"), {}) or {}
        if result.get("status") != "SUCCESS" or not any(
            _text(row.get("customization_name")) or _text(row.get("customization_initial"))
            for row in result.get("personalized_items", []) if isinstance(row, dict)
        ):
            continue
        conversations = (supabase_db.table("mercadolivre_chat_conversations").select("*")
                         .eq("marketplace_integration_id", account_id).eq("pack_id", pack_id)
                         .limit(1).execute().data or [])
        if not conversations:
            report["pending"].append({"log_id": log["id"], "pack_id": pack_id,
                                      "reason": "conversa não encontrada"})
            continue
        conversation = conversations[0]
        messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                    .eq("marketplace_integration_id", account_id).eq("pack_id", pack_id)
                    .order("created_at").execute().data or [])
        source = _json(log.get("input_data"), {}) or {}
        external_ids = [str(row.get("external_order_id")) for row in source.get("orders", [])]
        order_rows = (supabase_db.table("pedidos").select(
            "id,marketplace_order_id,codigo_pedido_externo,message_to_seller,marketplace_integration_id"
        ).eq("marketplace_integration_id", account_id).in_("marketplace_order_id", external_ids).execute().data or []) if external_ids else []
        order_ids = [int(row["id"]) for row in order_rows]
        items = (supabase_db.table("itens_pedido").select(
            "id,pedido_id,descricao,titulo_anuncio,quantidade"
        ).in_("pedido_id", order_ids).execute().data or []) if order_ids else []
        records, reason = _validate_log(log, conversation, messages, order_rows, items)
        if reason:
            report["pending"].append({"log_id": log["id"], "pack_id": pack_id, "reason": reason})
            continue
        if apply:
            response = supabase_db.rpc("restore_mercadolivre_personalizations_from_log", {
                "p_integration_id": account_id, "p_pack_id": pack_id,
                "p_log_id": int(log["id"]), "p_context_hash": _context_hash(messages),
                "p_records": records,
            }).execute()
            confirmation = getattr(response, "data", None)
            if isinstance(confirmation, list):
                confirmation = confirmation[0] if confirmation else None
            if not isinstance(confirmation, dict) or confirmation.get("source_log_id") != int(log["id"]):
                raise RuntimeError(f"Banco não confirmou recuperação do log {log['id']}")
            report["restored"].append({"log_id": log["id"], "pack_id": pack_id,
                                       "record_count": confirmation.get("saved", 0),
                                       "pedido_ids": sorted({r["pedido_id"] for r in records})})
        else:
            report["eligible"].append({"log_id": log["id"], "pack_id": pack_id,
                                       "record_count": len(records),
                                       "pedido_ids": sorted({r["pedido_id"] for r in records})})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration-id", type=int, help="Limita a recuperação a uma conta Mercado Livre")
    parser.add_argument("--apply", action="store_true", help="Grava resultados validados; padrão é simulação")
    args = parser.parse_args()
    print(json.dumps(run(integration_id=args.integration_id, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
