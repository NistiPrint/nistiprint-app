"""Configuração de IA de personalização isolada por instalação."""
from __future__ import annotations

import json
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.ai_personalization_service import get_ai_config


def _config_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _installation(integration_id: int) -> dict:
    rows = (supabase_db.table("installed_integrations")
            .select("id,module_id,instance_name,user_id,is_active,config")
            .eq("id", int(integration_id)).limit(1).execute().data or [])
    if not rows:
        raise LookupError("Conta conectada não encontrada")
    row = rows[0]
    module = str(row.get("module_id") or "").strip().lower()
    if module not in {"shopee", "mercadolivre"}:
        raise ValueError("A conta selecionada não é Shopee nem Mercado Livre")
    return {**row, "module_id": module, "config": _config_dict(row.get("config"))}


def list_accounts() -> list[dict]:
    rows = (supabase_db.table("installed_integrations")
            .select("id,module_id,instance_name,user_id,is_active,config")
            .in_("module_id", ["shopee", "mercadolivre"]).order("module_id").order("id")
            .execute().data or [])
    accounts = []
    for row in rows:
        module = str(row.get("module_id") or "").lower()
        if module not in {"shopee", "mercadolivre"}:
            continue
        cfg = _config_dict(row.get("config"))
        accounts.append({
            "integration_id": int(row["id"]),
            "marketplace": module,
            "marketplace_label": "Shopee" if module == "shopee" else "Mercado Livre",
            "name": row.get("instance_name") or cfg.get("name") or f"{module} #{row['id']}",
            "account_user_id": cfg.get("account_identifiers", {}).get("primary") or cfg.get("user_id") or row.get("user_id"),
            "is_active": bool(row.get("is_active")),
        })
    return accounts


def _shopee_config(integration_id: int) -> dict:
    rows = (supabase_db.table("shopee_personalization_ai_config").select("*")
            .eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if rows:
        return rows[0]
    current = get_ai_config()
    seed_row = {
        "marketplace_integration_id": int(integration_id),
        "prompt_template": current.get("prompt_template"),
        "provider": current.get("provider", "gemini"),
        "model_name": current.get("model_name", "gemini-2.5-flash"),
        "fallback_provider": current.get("fallback_provider"),
        "timeout_seconds": current.get("timeout_seconds", 60),
        "max_processing": current.get("max_processing", 50),
    }
    result = (supabase_db.table("shopee_personalization_ai_config")
              .upsert(seed_row, on_conflict="marketplace_integration_id").execute().data or [])
    return result[0] if result else seed_row


def get_config(integration_id: int) -> dict:
    installation = _installation(integration_id)
    if installation["module_id"] == "shopee":
        raw = _shopee_config(integration_id)
    else:
        from nistiprint_shared.services.mercadolivre_personalization_service import _settings, DEFAULT_PROMPT
        raw = _settings(integration_id)
        prompt_default = DEFAULT_PROMPT
    if installation["module_id"] == "shopee":
        prompt_default = ""
    return {
        "integration_id": int(integration_id),
        "marketplace": installation["module_id"],
        "prompt_template": raw.get("prompt_template") or prompt_default,
        "provider": raw.get("provider") or "gemini",
        "model_name": raw.get("model_name") or "gemini-2.5-flash",
        "fallback_provider": raw.get("fallback_provider") or "",
        "timeout_seconds": int(raw.get("timeout_seconds") or 60),
        "max_processing": int(raw.get("max_processing") or 50),
    }


def update_config(integration_id: int, values: dict, *, user_id: int | None = None) -> dict:
    installation = _installation(integration_id)
    from nistiprint_shared.services.ai.router import build_provider
    from nistiprint_shared.services.ai import PROVIDERS

    current = get_config(integration_id)
    update: dict[str, Any] = {}
    for key in ("prompt_template", "provider", "model_name", "fallback_provider", "timeout_seconds", "max_processing"):
        if key in values:
            update[key] = values[key]
    provider = str(update.get("provider", current["provider"])).strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("Provedor de IA inválido")
    model = str(update.get("model_name", current["model_name"])).strip()
    if not model or len(model) > 200:
        raise ValueError("Modelo inválido")
    build_provider(provider, model)
    fallback = str(update.get("fallback_provider", current["fallback_provider"]) or "").strip().lower()
    if fallback and (fallback not in PROVIDERS or fallback == provider):
        raise ValueError("Provedor de fallback inválido")
    if "prompt_template" in update and (not isinstance(update["prompt_template"], str) or len(update["prompt_template"]) > 30000):
        raise ValueError("Prompt deve ter até 30.000 caracteres")
    for key, default, maximum in (("timeout_seconds", current["timeout_seconds"], 600), ("max_processing", current["max_processing"], 500)):
        try:
            value = int(update.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} inválido") from exc
        if not 1 <= value <= maximum:
            raise ValueError(f"{key} deve estar entre 1 e {maximum}")
        update[key] = value
    update.update(provider=provider, model_name=model, fallback_provider=fallback or None)
    if installation["module_id"] == "shopee":
        update.update(marketplace_integration_id=int(integration_id), updated_by=user_id)
        supabase_db.table("shopee_personalization_ai_config").upsert(
            update, on_conflict="marketplace_integration_id").execute()
        return get_config(integration_id)
    from nistiprint_shared.services.mercadolivre_personalization_service import update_settings
    update_settings(integration_id, update, user_id=user_id)
    return get_config(integration_id)


def account_context(integration_id: int) -> dict:
    installation = _installation(integration_id)
    return {
        "integration_id": int(integration_id),
        "marketplace": installation["module_id"],
    }


def shopee_overrides(integration_id: int | None) -> dict | None:
    if integration_id is None:
        return None
    installation = _installation(int(integration_id))
    if installation["module_id"] != "shopee":
        return None
    raw = _shopee_config(int(integration_id))
    return {
        "prompt_template": raw.get("prompt_template"),
        "ia_provider": raw.get("provider"),
        "ia_model": raw.get("model_name"),
        "ia_fallback_provider": raw.get("fallback_provider"),
        "ia_timeout_seconds": raw.get("timeout_seconds"),
    }


def preview_config(integration_id: int, values: dict) -> dict:
    """Run the selected account's current conversation without saving results."""
    from nistiprint_shared.services.ai.router import build_provider, DEFAULT_MODEL_BY_PROVIDER
    from nistiprint_shared.database.supabase_db_service import supabase_db

    installation = _installation(integration_id)
    current = get_config(integration_id)
    config = {**current, **{key: values[key] for key in current if key in values}}
    provider = str(config.get("provider") or "gemini").lower()
    model = str(config.get("model_name") or DEFAULT_MODEL_BY_PROVIDER.get(provider, ""))
    fallback = str(config.get("fallback_provider") or "").lower()
    if fallback and fallback == provider:
        raise ValueError("O fallback precisa ser diferente do provedor principal")
    build_provider(provider, model)
    overrides = {
        "prompt_template": config.get("prompt_template"), "ia_provider": provider,
        "ia_model": model, "ia_fallback_provider": fallback,
        "ia_timeout_seconds": config.get("timeout_seconds", 60),
    }
    if installation["module_id"] == "shopee":
        orders = (supabase_db.table("pedidos").select("id,marketplace_integration_id")
                  .eq("marketplace_integration_id", int(integration_id))
                  .order("data_venda", desc=True).limit(20).execute().data or [])
        if not orders:
            raise LookupError("Não há pedido desta conta para testar o prompt")
        from nistiprint_shared.services.ai_personalization_service import (
            _load_order_for_ai, generate_prompt_payload, run_model_detailed,
        )
        order = None
        for row in orders:
            try:
                candidate = _load_order_for_ai(int(row["id"]))
                if candidate.get("marketplace_integration_id") == int(integration_id):
                    order = candidate
                    break
            except (ValueError, LookupError):
                continue
        if not order:
            raise LookupError("Não há conversa carregada para um pedido desta conta")
        if (order.get("chat_gate") or {}).get("acao") == "adiar":
            raise ValueError("A conversa de teste ainda está sendo sincronizada")
        result, response = run_model_detailed(generate_prompt_payload(order), config_overrides=overrides)
    else:
        from nistiprint_shared.services.mercadolivre_personalization_service import (
            _ai_response, _pack_context, available_integrations,
        )
        account = next((row for row in available_integrations()
                        if int(row["integration_id"]) == int(integration_id)), None)
        if not account or not account.get("is_active") or not account.get("application_id_configured"):
            raise ValueError("A conta Mercado Livre precisa estar ativa e com OAuth válido")
        orders = supabase_db.table("mercadolivre_chat_conversations").select("pack_id").eq(
            "marketplace_integration_id", int(integration_id)
        ).order("last_message_at", desc=True).limit(1).execute().data or []
        if not orders:
            raise LookupError("Não há conversa Mercado Livre sincronizada para testar")
        pack_id = str(orders[0]["pack_id"])
        pack_orders, items, _digest, _review = _pack_context(int(integration_id), pack_id)
        messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                    .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", pack_id)
                    .order("created_at").execute().data or [])
        if not pack_orders or not items or not messages:
            raise LookupError("A conversa selecionada ainda não tem pedidos e itens associados")
        payload = {
            "pack_id": pack_id,
            "orders": [{"pedido_id": order["id"],
                        "external_order_id": order.get("marketplace_order_id") or order.get("codigo_pedido_externo"),
                        "items": [{"item_id": item["id"],
                                   "description": item.get("titulo_anuncio") or item.get("descricao"),
                                   "quantity": item.get("quantidade", 1)}
                                  for item in items if int(item["pedido_id"]) == int(order["id"])]}
                       for order in pack_orders],
            "messages": [{"id": msg.get("provider_message_id"), "sender_role": msg.get("sender_role"),
                          "created_at": msg.get("created_at"), "text": msg.get("text_content"),
                          "attachments": msg.get("attachments") or []} for msg in messages],
        }
        import json
        result, response = _ai_response(
            int(integration_id), {**config, "model_name": model},
            str(config.get("prompt_template") or ""),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    return {"result": result, "model": response.to_metadata(), "saved": False}
