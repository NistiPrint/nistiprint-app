"""Private post-sale chat ingestion and account-isolated personalization."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.marketplace_account_identity import account_identity_matches
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver

logger = logging.getLogger(__name__)
AGENT_IDS = {"3037675074", "3020819166", "3037204123", "3037204279", "3037674934", "3037204685"}
DEFAULT_PROMPT = """Extraia personalizações dos pedidos do Mercado Livre usando somente as instruções do comprador nos dados recebidos. Leia mensagem ao vendedor e conversa em ordem cronológica; aplique correções posteriores do comprador e preserve grafia e acentos. Nunca use nome cadastral, apelido ou mensagem de agente como personalização. Cada resultado deve usar exatamente um item_id interno recebido e a quantidade total daquele item não pode ser excedida. Nomes diferentes por unidade exigem uma linha por nome e quantity_to_personalize=1; um mesmo nome em várias unidades pode ser uma linha com a quantidade total. Toda linha com nome ou inicial precisa indicar o ID exato da mensagem do comprador que a comprova; mensagem ao vendedor usa name_source_message_id=\"message_to_seller\". Sem personalização inequívoca, retorne uma linha para cada item com nome e inicial nulos, quantidade total e fontes nulas, status NO_PERSONALIZATION_FOUND. Use SUCCESS se pelo menos um nome ou inicial inequívoco foi extraído; NEEDS_REVIEW se contexto, item, quantidade ou anexo necessário for ambíguo/incompleto; nesse caso retorne as linhas ainda determináveis e nulos para o que não puder ser atribuído. Não omita itens elegíveis. Exemplos: um item de quantidade 1 e mensagem ‘Nome: Ana’ → uma linha do item, Ana, quantidade 1, fonte da mensagem; item de quantidade 2 e mensagem ‘Ana e Bia’ → duas linhas de quantidade 1; ‘letra M’ → inicial M e fonte da mensagem; nenhuma instrução → linha sem nome/inicial; duas mensagens contraditórias sem correção clara → NEEDS_REVIEW. Responda somente o objeto JSON definido pelo schema da requisição."""
LEGACY_DEFAULT_PROMPT = """Você extrai dados de personalização de pedidos do Mercado Livre. Analise os itens, a mensagem ao vendedor e a conversa completa em ordem cronológica. Use as instruções do comprador, preserve exatamente a grafia, os acentos e a correção mais recente para cada nome ou inicial. Uma confirmação do vendedor pode ajudar a entender o contexto, mas não substitui a instrução do comprador. Se a mensagem ao vendedor contiver a personalização e não houver correção posterior, use-a com name_source_message_id=\"message_to_seller\". Nunca use nome de cadastro ou apelido como personalização. Associe cada resultado ao item correto; para nomes distintos em várias unidades, devolva uma linha por unidade; se um nome valer para todas, devolva uma linha com a quantidade total. Retorne uma linha sem nome quando não houver instrução inequívoca. Use NEEDS_REVIEW somente se o contexto estiver incompleto, a atribuição de item/pedido for ambígua, um anexo for necessário para entender o pedido ou a quantidade for incompatível. Responda somente JSON: {\"status\":\"SUCCESS|NEEDS_REVIEW|NO_PERSONALIZATION_FOUND\",\"reasoning\":\"...\",\"personalized_items\":[{\"item_id\":\"ID interno informado\",\"quantity_to_personalize\":1,\"customization_name\":null,\"name_source_message_id\":null,\"customization_initial\":null,\"initial_source_message_id\":null}]}"""

PERSONALIZATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["SUCCESS", "NEEDS_REVIEW", "NO_PERSONALIZATION_FOUND"]},
        "reasoning": {"type": "string"},
        "personalized_items": {"type": "array", "items": {
            "type": "object", "properties": {
                "item_id": {"type": "integer"},
                "quantity_to_personalize": {"type": "integer", "minimum": 1},
                "customization_name": {"type": ["string", "null"]},
                "name_source_message_id": {"type": ["string", "null"]},
                "customization_initial": {"type": ["string", "null"]},
                "initial_source_message_id": {"type": ["string", "null"]},
            }, "required": ["item_id", "quantity_to_personalize", "customization_name",
                           "name_source_message_id", "customization_initial", "initial_source_message_id"],
            "additionalProperties": False,
        }},
    }, "required": ["status", "reasoning", "personalized_items"], "additionalProperties": False,
}


class ProviderRetryError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        self.retry_after = max(1.0, float(retry_after)) if retry_after is not None else None
        super().__init__("retry:" + message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            pass
    return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _source_metadata(row: dict) -> dict:
    details = _json(row.get("details"), {}) or {}
    return {**details,
            "name_source_message_id": details.get("name_source_message_id") or row.get("provider_message_id"),
            "initial_source_message_id": details.get("initial_source_message_id")}


def _profile_application_id(profile_id: Any, module_id: Any) -> str | None:
    """Return this profile's Mercado Livre application ID from its encrypted client_id."""
    if not profile_id:
        return None
    profile = (supabase_db.table("integration_app_profiles").select("id,module_id,is_active")
               .eq("id", profile_id).limit(1).execute().data or [])
    if (not profile or str(profile[0].get("module_id")) != str(module_id)
            or profile[0].get("is_active") is False):
        return None
    from nistiprint_shared.services.integration_secret_service import integration_secret_service
    secrets = integration_secret_service.get_secret_map("app_profile", profile_id)
    application_id = _text(secrets.get("client_id") or secrets.get("app_id"))
    return application_id or None


def _integration(integration_id: int, *, active: bool = True) -> dict:
    query = supabase_db.table("installed_integrations").select(
        "id,module_id,user_id,is_active,config,credentials,access_token,refresh_token,app_profile_id"
    ).eq("id", int(integration_id))
    if active:
        query = query.eq("is_active", True)
    rows = query.limit(1).execute().data or []
    if not rows:
        raise ValueError("Conta Mercado Livre inexistente ou inativa")
    installed = rows[0]
    module_id = installed.get("module_id")
    if str(module_id or "").strip().lower() != "mercadolivre":
        raise ValueError("A instalação informada não é do Mercado Livre")
    if not installed.get("app_profile_id"):
        raise ValueError("Vincule esta conta ao seu próprio aplicativo OAuth antes de usar as mensagens")
    if not _profile_application_id(installed["app_profile_id"], module_id):
        raise ValueError("O perfil OAuth desta conta não possui application_id válido")
    from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
    return credential_resolver_service.hydrate_integration(installed)


def _settings(integration_id: int) -> dict:
    rows = (supabase_db.table("mercadolivre_personalization_config").select("*")
            .eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if rows:
        current = rows[0]
        prompt = current.get("prompt_template")
        if not isinstance(prompt, str) or len(prompt.strip()) < 40 or prompt.strip() == LEGACY_DEFAULT_PROMPT:
            update = {"prompt_template": DEFAULT_PROMPT, "updated_at": _now()}
            if prompt:
                update["previous_prompt_template"] = prompt
            saved = (supabase_db.table("mercadolivre_personalization_config").update(update)
                     .eq("marketplace_integration_id", int(integration_id)).execute().data or [])
            current = saved[0] if saved else {**current, **update}
        return current
    seed = {"marketplace_integration_id": int(integration_id), "enabled": True,
            "capture_enabled": True, "extraction_enabled": True, "schedule_enabled": True}
    result = supabase_db.table("mercadolivre_personalization_config").upsert(
        seed, on_conflict="marketplace_integration_id").execute().data or []
    return result[0] if result else seed


def _preserve_previous_prompt(integration_id: int, current: dict, next_prompt: str) -> dict:
    prior = str(current.get("prompt_template") or "")
    if not prior.strip() or prior == next_prompt:
        return {}
    return {"previous_prompt_template": prior}


def available_integrations() -> list[dict]:
    modules = (supabase_db.table("integration_modules").select("id")
               .eq("id", "mercadolivre").limit(1).execute().data or [])
    if not modules:
        return []
    rows = (supabase_db.table("installed_integrations").select(
        "id,module_id,user_id,instance_name,is_active,config,app_profile_id"
    ).eq("module_id", modules[0]["id"]).order("id").execute().data or [])
    output = []
    for row in rows:
        ident = int(row["id"])
        settings = _settings(ident)
        config = row.get("config") or {}
        account = ((config.get("account_identifiers") or {}).get("primary")
                   or config.get("user_id") or row.get("user_id"))
        application_id = _profile_application_id(row.get("app_profile_id"), row.get("module_id"))
        output.append({"integration_id": ident,
                       "name": row.get("instance_name") or config.get("name") or f"Mercado Livre #{ident}",
                       "account_user_id": str(account) if account is not None else None,
                       "application_id_configured": bool(application_id),
                       "is_active": bool(row.get("is_active")),
                       "enabled": bool(settings.get("enabled")),
                       "capture_enabled": bool(settings.get("capture_enabled")),
                       "extraction_enabled": bool(settings.get("extraction_enabled")),
                       "schedule_enabled": bool(settings.get("schedule_enabled", True)),
                       "schedule_hour": settings.get("schedule_hour", 9),
                       "schedule_minute": settings.get("schedule_minute", 0),
                       "last_scheduled_run_date": settings.get("last_scheduled_run_date")})
    return output


def update_settings(integration_id: int, values: dict, *, user_id: int | None = None) -> dict:
    _integration(integration_id, active=False)
    current = _settings(integration_id)
    allowed = {"schedule_enabled", "provider", "model_name",
               "fallback_provider", "timeout_seconds", "max_processing", "schedule_hour",
               "schedule_minute", "prompt_template"}
    update = {key: values[key] for key in allowed if key in values}
    if "prompt_template" in update:
        update.update(_preserve_previous_prompt(integration_id, current, update["prompt_template"]))
    if "prompt_template" in update:
        prior_prompt = str(current.get("prompt_template") or "")
        if prior_prompt.strip() and prior_prompt != update["prompt_template"]:
            update["previous_prompt_template"] = prior_prompt
    for key in ("schedule_enabled",):
        if key in update and not isinstance(update[key], bool):
            raise ValueError(f"{key} precisa ser booleano")
    provider = update.get("provider", current.get("provider", "gemini"))
    if provider not in {"gemini", "openrouter"}:
        raise ValueError("Provedor de IA inválido")
    if "fallback_provider" in update and not update["fallback_provider"]:
        update["fallback_provider"] = None
    if update.get("fallback_provider", current.get("fallback_provider")) == provider:
        raise ValueError("O fallback precisa ser diferente do provedor principal")
    for key, lower, upper in (("timeout_seconds", 1, 600), ("max_processing", 1, 500),
                              ("schedule_hour", 0, 23), ("schedule_minute", 0, 59)):
        if key in update:
            try:
                number = int(update[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} inválido") from exc
            if not lower <= number <= upper:
                raise ValueError(f"{key} fora do intervalo permitido")
            update[key] = number
    if "model_name" in update:
        model = str(update["model_name"]).strip()
        if not model or len(model) > 200:
            raise ValueError("Modelo inválido")
        from nistiprint_shared.services.ai.router import build_provider
        build_provider(provider, model)
        update["model_name"] = model
    if "prompt_template" in update and (not isinstance(update["prompt_template"], str)
                                         or len(update["prompt_template"]) > 30000):
        raise ValueError("Prompt deve ser texto de até 30.000 caracteres")
    update.update(updated_at=_now(), updated_by=user_id)
    rows = (supabase_db.table("mercadolivre_personalization_config")
            .upsert({"marketplace_integration_id": int(integration_id), **update},
                    on_conflict="marketplace_integration_id").execute().data or [])
    return rows[0] if rows else {**current, **update}


def _notification_account_candidates(user_id: str | None, application_id: str | None) -> tuple[int | None, int | None]:
    modules = (supabase_db.table("integration_modules").select("id")
               .eq("id", "mercadolivre").limit(1).execute().data or [])
    if not modules:
        return None, None
    rows = (supabase_db.table("installed_integrations").select(
        "id,module_id,user_id,is_active,config,credentials,app_profile_id"
    ).eq("module_id", modules[0]["id"]).eq("is_active", True).execute().data or [])
    user_matches = ([row for row in rows if account_identity_matches(row, str(user_id))
                     or str(row.get("user_id") or "") == str(user_id)]
                    if user_id else [])
    app_matches = []
    if application_id:
        for row in rows:
            profile_application_id = _profile_application_id(
                row.get("app_profile_id"), row.get("module_id")
            )
            if profile_application_id == str(application_id):
                app_matches.append(row)
    user_ids = {int(row["id"]) for row in user_matches}
    app_ids = {int(row["id"]) for row in app_matches}
    exact_ids = user_ids & app_ids if user_id and application_id else set()
    exact = next(iter(exact_ids)) if len(exact_ids) == 1 and len(user_ids) == 1 else None
    if exact:
        return exact, exact
    # A single reliable dimension can anchor an audit item, but never authorize
    # processing. Conflicting account and application identities remain global.
    if user_ids and app_ids:
        return None, None
    candidates = user_ids or app_ids
    audit_owner = next(iter(candidates)) if len(candidates) == 1 else None
    return None, audit_owner


def _resolve_notification_account(user_id: str, application_id: str) -> int | None:
    return _notification_account_candidates(user_id, application_id)[0]


def enqueue_notification(payload: dict, *, webhook_event_id: int | None = None) -> dict:
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    body = {**payload, **nested}
    account = _text(body.get("user_id") or payload.get("user_id"))
    app_id = _text(body.get("application_id") or payload.get("application_id"))
    resource = _text(body.get("resource") or payload.get("resource") or body.get("id"))
    # Mercado Livre sends both `/messages/<id>` and full API resources such as
    # `https://api.mercadolibre.com/messages/<id>`. Parse the path so query
    # strings or host prefixes never become part of the opaque message ID.
    message_match = re.search(r"(?:^|/)messages/([^/?#]+)", resource)
    message_id = message_match.group(1) if message_match else resource
    resource_valid = bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", message_id or ""))
    if not resource_valid:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        message_id = "unresolved-" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    account = account or None
    app_id = app_id or None
    exact_integration_id, audit_owner_id = _notification_account_candidates(account, app_id)
    if not resource_valid:
        exact_integration_id = None
    actions = body.get("actions") or []
    if not isinstance(actions, list):
        actions = [actions]
    record = {"marketplace_integration_id": exact_integration_id or audit_owner_id,
              "account_user_id": account,
              "application_id": app_id, "provider_message_id": message_id,
              "webhook_event_id": webhook_event_id,
              "actions": [str(action)[:60] for action in actions], "raw_payload": payload,
              "status": "pending" if exact_integration_id else "unmatched", "available_at": _now()}
    # Keep the delivery ID for audit, while deduplicating by account and opaque
    # provider message ID so repeated actions still cause one history sync.
    delivery_id = _text(body.get("_id") or payload.get("_id") or body.get("id")) or f"{message_id}:{','.join(record['actions'])}:{body.get('sent', payload.get('sent', ''))}"
    record["provider_message_id"] = str(message_id)
    record["raw_payload"] = {**payload, "_delivery_id": delivery_id,
                              "_identity_complete": bool(account and app_id),
                              "_identity_matched": bool(exact_integration_id),
                              "_resource_valid": resource_valid}
    identity = json.dumps([app_id, account, str(message_id)], ensure_ascii=False, separators=(",", ":"))
    record["dedupe_key"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    response = supabase_db.table("mercadolivre_chat_inbox").upsert(
        record, on_conflict="dedupe_key").execute()
    saved = (response.data or [{}])[0]
    return {"status": "success", "event_status": "pending_private_chat",
            "marketplace_integration_id": exact_integration_id,
            "identity_status": "matched" if exact_integration_id else "unmatched",
            "inbox_id": saved.get("id"), "resource_id": message_id}


def message_consumer_accounts() -> list[dict]:
    """Return active accounts whose webhook identity can be matched safely."""
    modules = (supabase_db.table("integration_modules").select("id")
               .eq("id", "mercadolivre").limit(1).execute().data or [])
    if not modules:
        return []
    rows = (supabase_db.table("installed_integrations").select(
        "id,module_id,user_id,is_active,config,app_profile_id"
    ).eq("module_id", modules[0]["id"]).eq("is_active", True).order("id").execute().data or [])
    accounts = []
    for row in rows:
        config = _json(row.get("config"), {}) or {}
        seller_id = _text(((config.get("account_identifiers") or {}).get("primary")
                           or config.get("user_id") or row.get("user_id")))
        application_id = _profile_application_id(row.get("app_profile_id"), row.get("module_id"))
        if seller_id and application_id:
            accounts.append({**row, "integration_id": int(row["id"]),
                             "seller_id": seller_id, "application_id": application_id})
    return accounts


def _claim_notifications(integration_ids: list[int], limit: int = 25) -> list[dict]:
    integration_ids = sorted({int(value) for value in integration_ids if value is not None})
    if not integration_ids:
        return []
    now = _now()
    stale = (supabase_db.table("mercadolivre_chat_inbox").update({"status": "retry", "lease_until": None})
             .in_("marketplace_integration_id", integration_ids).eq("status", "processing")
             .lt("lease_until", now).execute())
    del stale
    candidates = (supabase_db.table("mercadolivre_chat_inbox").select("*")
                  .in_("marketplace_integration_id", integration_ids).in_("status", ["pending", "retry"])
                  .lte("available_at", now).order("created_at").limit(min(max(int(limit), 1), 100)).execute().data or [])
    claimed = []
    for row in candidates:
        changed = (supabase_db.table("mercadolivre_chat_inbox").update({
            "status": "processing", "lease_until": datetime.fromtimestamp(time.time() + 120, timezone.utc).isoformat(),
            "attempts": int(row.get("attempts") or 0) + 1, "updated_at": now,
        }).eq("id", row["id"]).in_("status", ["pending", "retry"]).execute().data or [])
        if changed:
            claimed.extend(changed)
    return claimed


def _resolve_unmatched_for_account(integration_id: int, integration: dict, seller_id: str) -> int:
    profile_id = integration.get("app_profile_id")
    if not profile_id or not seller_id:
        return 0
    application_id = _profile_application_id(profile_id, integration.get("module_id"))
    if not application_id:
        return 0
    rows = (supabase_db.table("mercadolivre_chat_inbox").select("id,account_user_id,application_id")
            .eq("status", "unmatched").eq("account_user_id", str(seller_id))
            .eq("application_id", application_id).order("created_at").limit(100).execute().data or [])
    matched = 0
    for row in rows:
        resolved = _resolve_notification_account(str(row["account_user_id"]), str(row["application_id"]))
        if resolved != int(integration_id):
            continue
        changed = (supabase_db.table("mercadolivre_chat_inbox").update({
            "marketplace_integration_id": int(integration_id), "status": "pending",
            "available_at": _now(), "updated_at": _now(),
        }).eq("id", row["id"]).eq("status", "unmatched").execute().data or [])
        matched += len(changed)
    return matched


def _parse_created(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _message_created_at(message: dict) -> str | None:
    dates = message.get("message_date")
    created = dates.get("created") if isinstance(dates, dict) else None
    return _parse_created(created or message.get("date_created") or message.get("date"))


def _normalize_order_ids(values: Any) -> list[str]:
    """Return provider order IDs without stringifying pack order objects."""
    if not isinstance(values, list):
        raise ValueError("resposta de pacote sem lista de pedidos")
    normalized = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("id")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("resposta de pacote contém pedido sem ID válido")
        order_id = str(value).strip()
        if not order_id or len(order_id) > 160:
            raise ValueError("resposta de pacote contém pedido sem ID válido")
        normalized.append(order_id)
    return list(dict.fromkeys(normalized))


def _messages_from_response(response: dict) -> list[dict]:
    if isinstance(response.get("error"), str):
        retryable = bool(response.get("retryable"))
        if retryable:
            raise ProviderRetryError(response["error"], response.get("retry_after"))
        raise RuntimeError("terminal:" + response["error"])
    messages = response.get("messages")
    return messages if isinstance(messages, list) else []


def _message_text(message: dict) -> str:
    text = message.get("text")
    if isinstance(text, dict):
        return _text(text.get("plain") or text.get("html"))
    return _text(text)


def _upsert_messages(integration_id: int, pack_id: str, seller_id: str,
                     messages: list[dict], webhook_event_id: int | None,
                     buyer_ids: set[str] | None = None) -> list[dict]:
    buyer_ids = buyer_ids or set()
    records = []
    for message in messages:
        msg_id = _text(message.get("message_id") or message.get("id"))
        if not msg_id:
            continue
        sender = _text((message.get("from") or {}).get("user_id"))
        receiver = _text((message.get("to") or {}).get("user_id"))
        if sender == str(seller_id):
            role = "seller"
        elif sender in AGENT_IDS:
            role = "agent"
        elif sender and sender in buyer_ids:
            role = "buyer"
        else:
            role = "unknown"
        text = _message_text(message)
        attachments_value = message.get("attachments")
        if not isinstance(attachments_value, list):
            attachments_value = message.get("message_attachments")
        attachments = attachments_value if isinstance(attachments_value, list) else []
        moderation = message.get("moderation") or {}
        records.append({
            "marketplace_integration_id": int(integration_id), "provider_message_id": msg_id,
            "pack_id": str(pack_id), "seller_id": str(seller_id), "from_user_id": sender or None,
            "to_user_id": receiver or None, "sender_role": role,
            "message_type": "attachment" if attachments and not text else "text",
            "text_content": text or None, "created_at": _message_created_at(message),
            "moderation_status": _text(message.get("status") or moderation.get("status")) or None,
            "attachments": attachments, "raw_json": message,
            "webhook_event_id": webhook_event_id, "updated_at": _now(),
        })
    if records:
        (supabase_db.table("mercadolivre_chat_messages")
         .upsert(records, on_conflict="marketplace_integration_id,provider_message_id").execute())
    return records


def _context_hash(messages: list[dict]) -> str:
    canonical = [{"id": message.get("provider_message_id"), "role": message.get("sender_role"),
                  "text": message.get("text_content"), "created_at": message.get("created_at"),
                  "moderation": message.get("moderation_status"), "attachments": message.get("attachments") or []}
                 for message in sorted(messages, key=lambda row: (str(row.get("created_at") or ""),
                                                                     str(row.get("provider_message_id") or "")))]
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _meli_request(integration_id: int, endpoint: str, function, *args, **kwargs):
    from nistiprint_shared.services.mercadolivre_rate_limit import (
        mercadolivre_rate_limit_coordinator,
    )
    mercadolivre_rate_limit_coordinator.acquire(int(integration_id), endpoint)
    return function(*args, **kwargs)


def _pack_order_ids(integration_id: int, integration: dict, pack_id: str) -> list[str]:
    pack = _meli_request(integration_id, "packs", meli_driver.get_pack, integration, pack_id)
    if pack.get("error"):
        if pack.get("retryable"):
            raise ProviderRetryError(pack["error"], pack.get("retry_after"))
        # A conversation may still be available through /messages/packs/{id}
        # when the optional /packs/{id} metadata endpoint does not find it.
        # This also covers orders whose pack_id is null and use order_id instead.
        if int(pack.get("status_code") or 0) == 404:
            logger.info("Mercado Livre pack metadata unavailable; continuing with conversation integration=%s pack=%s",
                        integration_id, pack_id)
            return []
        raise RuntimeError("terminal:" + pack["error"])
    return _normalize_order_ids(pack.get("orders") or pack.get("orders_ids") or [])


def _mark_inbox_messages_persisted(integration_id: int, messages: list[dict]) -> None:
    """Complete inbox events only after their provider message was persisted."""
    message_ids = list(dict.fromkeys(
        _text(message.get("provider_message_id")) for message in messages
        if _text(message.get("provider_message_id"))
    ))
    if not message_ids:
        return
    (supabase_db.table("mercadolivre_chat_inbox")
     .update({"status": "done", "lease_until": None, "last_error": None, "updated_at": _now()})
     .eq("marketplace_integration_id", int(integration_id))
     .in_("provider_message_id", message_ids)
     .in_("status", ["pending", "retry", "processing"])
     .execute())


def sync_pack(integration_id: int, pack_id: str, seller_id: str,
              webhook_event_id: int | None = None,
              order_id_fallback: str | None = None) -> dict:
    integration = _integration(integration_id)
    existing = (supabase_db.table("mercadolivre_chat_conversations").select("id,raw_json,order_ids,needs_review")
                .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
                .eq("seller_id", str(seller_id)).limit(1).execute().data or [])
    orders = ([str(order_id_fallback)] if order_id_fallback else
              _pack_order_ids(integration_id, integration, pack_id))
    if not orders and existing:
        try:
            orders = _normalize_order_ids(_json(existing[0].get("order_ids"), []) or [])
        except ValueError:
            orders = []
    if not orders and str(pack_id).isdigit():
        orders = [str(pack_id)]
    all_messages: list[dict] = []
    offset, page_size = 0, 50
    total = None
    for _ in range(20):
        response = _meli_request(
            integration_id, "messages", meli_driver.get_post_sale_messages,
            integration, str(pack_id), str(seller_id), offset=offset,
            limit=page_size, mark_as_read=False,
        )
        page = _messages_from_response(response)
        paging = response.get("paging") or {}
        total = int(paging.get("total") or total or len(page))
        all_messages.extend(page)
        if not page or offset + len(page) >= total:
            break
        offset += len(page)
    else:
        raise RuntimeError("retry:histórico de mensagens excedeu o limite de páginas")
    metadata = _json(existing[0].get("raw_json"), {}) if existing else {}
    cached_buyers = metadata.get("buyer_ids") if isinstance(metadata, dict) else None
    buyer_ids = {str(value) for value in cached_buyers or []}
    if not buyer_ids or set(orders) != {str(value) for value in (existing[0].get("order_ids") or [])}:
        for order_id in orders:
            try:
                order_detail = _meli_request(
                    integration_id, "orders", meli_driver.get_order_detail,
                    integration, [str(order_id)],
                )
                if order_detail.get("error"):
                    if order_detail.get("retryable"):
                        raise ProviderRetryError(order_detail["error"], order_detail.get("retry_after"))
                    continue
                buyer = order_detail.get("buyer") or {}
                if buyer.get("id") is not None:
                    buyer_ids.add(str(buyer["id"]))
            except Exception:
                logger.info("Could not resolve buyer identity integration=%s order=%s", integration_id, order_id)
    rows = _upsert_messages(integration_id, str(pack_id), str(seller_id), all_messages,
                            webhook_event_id, buyer_ids=buyer_ids)
    current_messages = (supabase_db.table("mercadolivre_chat_messages").select(
        "provider_message_id,sender_role,text_content,created_at,moderation_status,attachments"
    ).eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
      .order("created_at").execute().data or [])
    _mark_inbox_messages_persisted(integration_id, rows)
    needs_review = any(row["sender_role"] == "unknown"
                       or (row.get("attachments") and not _text(row.get("text_content")))
                       or row.get("moderation_status") not in {None, "", "available"}
                       for row in rows)
    site_id = next((_text(message.get("site_id")) for message in all_messages if message.get("site_id")), None)
    # Update existing state without overwriting the AI context hash or review state.
    conversation_fields = {
        "site_id": site_id, "order_ids": orders,
        "last_message_at": max((_message_created_at(message) or "" for message in all_messages), default="") or None,
        "last_synced_at": _now(), "raw_json": {"paging_total": total,
            "order_id_fallback": str(order_id_fallback) if order_id_fallback else None,
            "buyer_ids": sorted(buyer_ids)}, "current_context_hash": _context_hash(current_messages),
        "updated_at": _now(),
    }
    if needs_review:
        conversation_fields["needs_review"] = True
    query = supabase_db.table("mercadolivre_chat_conversations")
    if existing:
        query.update(conversation_fields).eq("id", existing[0]["id"]).execute()
    else:
        query.insert({"marketplace_integration_id": int(integration_id), "pack_id": str(pack_id),
                      "seller_id": str(seller_id), "needs_review": needs_review,
                      **conversation_fields}).execute()
    return {"status": "success", "pack_id": str(pack_id), "orders": orders,
            "messages": len(rows), "needs_review": needs_review}


def process_inbox_once(integration_ids: list[int] | None = None, *, limit: int = 25) -> dict:
    """Consume matched notifications for all selected accounts in one marketplace worker."""
    accounts = message_consumer_accounts()
    if integration_ids is not None:
        requested = {int(value) for value in integration_ids}
        accounts = [account for account in accounts if account["integration_id"] in requested]
    eligible_ids = [account["integration_id"] for account in accounts]
    for account in accounts:
        try:
            _resolve_unmatched_for_account(
                account["integration_id"], account, account["seller_id"]
            )
        except Exception:
            logger.exception("Could not resolve unmatched Mercado Livre notifications integration=%s",
                             account["integration_id"])
    entries = _claim_notifications(eligible_ids, limit)
    result = {"claimed": len(entries), "synced": 0, "retried": 0, "failed": 0}
    for entry in entries:
        integration_id = int(entry.get("marketplace_integration_id") or 0)
        try:
            if integration_id not in eligible_ids:
                raise RuntimeError("terminal:integração da notificação não está ativa ou identificável")
            integration = _integration(integration_id)
            seller_id = _text(((integration.get("config") or {}).get("account_identifiers") or {}).get("primary")
                              or (integration.get("config") or {}).get("user_id") or integration.get("user_id"))
            if not seller_id:
                raise RuntimeError("terminal:conta conectada sem user_id em account_identifiers")
            raw = entry.get("raw_payload") or {}
            actions = raw.get("actions") or []
            if "created" not in actions and "updated" not in actions and "read" not in actions:
                supabase_db.table("mercadolivre_chat_inbox").update({"status": "done", "lease_until": None,
                    "updated_at": _now()}).eq("id", entry["id"]).eq("status", "processing").execute()
                continue
            detail = _meli_request(
                integration_id, "messages", meli_driver.get_message,
                integration, entry["provider_message_id"],
            )
            if detail.get("error"):
                if detail.get("retryable"):
                    raise ProviderRetryError(detail["error"], detail.get("retry_after"))
                raise RuntimeError("terminal:" + detail["error"])
            # Most accounts return the message fields at the root. Some API
            # responses wrap the message in a one-element `messages` list.
            message_detail = detail
            nested_messages = detail.get("messages")
            if isinstance(nested_messages, list) and nested_messages:
                message_detail = next((message for message in nested_messages
                                       if _text(message.get("message_id") or message.get("id"))
                                       == str(entry["provider_message_id"])), nested_messages[0])
            resources = message_detail.get("message_resources") or detail.get("message_resources") or []
            pack_id = next((_text(r.get("id")) for r in resources if r.get("name") == "packs"), "")
            fallback_order_id = next((_text(r.get("id")) for r in resources if r.get("name") == "orders"), "")
            message_seller = next((_text(r.get("id")) for r in resources if r.get("name") == "seller"), "")
            detail_resource = str(message_detail.get("resource") or detail.get("resource") or "")
            if not pack_id:
                pack_id = next((_text(detail_resource.split("/")[2])
                                for _ in [0] if detail_resource.startswith("/packs/")), "")
            if not pack_id and not fallback_order_id:
                fallback_order_id = next((_text(detail_resource.split("/")[2])
                                          for _ in [0] if detail_resource.startswith("/orders/")), "")
            if not pack_id and fallback_order_id:
                pack_id = fallback_order_id
            if not pack_id:
                raise RuntimeError("retry:mensagem ainda sem recurso de pack")
            sync_pack(integration_id, pack_id, message_seller or seller_id,
                      int(entry["webhook_event_id"]) if entry.get("webhook_event_id") else None,
                      order_id_fallback=fallback_order_id or None)
            supabase_db.table("mercadolivre_chat_inbox").update({"status": "done", "lease_until": None,
                "last_error": None, "updated_at": _now()}).eq("id", entry["id"]).eq("status", "processing").execute()
            result["synced"] += 1
        except Exception as exc:
            retry = (str(exc).startswith("retry:") or getattr(exc, "retry_after", None) is not None
                     or int(entry.get("attempts") or 0) < 3)
            attempts = int(entry.get("attempts") or 0)
            update = {"status": "retry" if retry else "failed", "lease_until": None,
                      "last_error": str(exc)[:1000], "updated_at": _now()}
            if retry:
                retry_after = getattr(exc, "retry_after", None)
                update["available_at"] = datetime.fromtimestamp(
                    time.time() + max(min(3600, 30 * (2 ** min(attempts - 1, 7))),
                                      min(3600, float(retry_after or 0))), timezone.utc).isoformat()
            supabase_db.table("mercadolivre_chat_inbox").update(update).eq("id", entry["id"]).eq("status", "processing").execute()
            result["retried" if retry else "failed"] += 1
            logger.warning("Mercado Livre inbox failure integration=%s inbox=%s: %s", integration_id, entry["id"], exc)
    return result


def _reconcile_account_once(integration_id: int, *, limit: int = 25) -> dict:
    integration = _integration(integration_id)
    seller_id = _text(((integration.get("config") or {}).get("account_identifiers") or {}).get("primary")
                      or (integration.get("config") or {}).get("user_id") or integration.get("user_id"))
    unread = _meli_request(
        integration_id, "unread", meli_driver.get_unread_post_sale_conversations,
        integration, role="seller",
    )
    if unread.get("error"):
        if unread.get("retryable"):
            raise ProviderRetryError(unread["error"], unread.get("retry_after"))
        raise RuntimeError("terminal:" + unread["error"])
    resources = unread.get("results") or []
    scanned: set[tuple[str, str]] = set()
    unread_synced = 0
    for resource in resources[:min(max(int(limit), 1), 50)]:
        path = str(resource.get("resource") or "")
        match = re.search(r"/(packs|orders)/([^/]+)/(?:sellers?|seller)/([^/?]+)", path)
        if not match:
            continue
        kind, resource_id, resource_seller_id = match.groups()
        is_order = kind == "orders"
        conversation_key = (resource_id, resource_seller_id or seller_id)
        scanned.add(conversation_key)
        try:
            sync_pack(integration_id, resource_id, resource_seller_id or seller_id,
                      order_id_fallback=resource_id if is_order else None)
            unread_synced += 1
        except Exception as exc:
            logger.exception("Mercado Livre unread recovery failed integration=%s resource=%s", integration_id, path)
            # A provider rate limit applies to the whole account. Stop this
            # reconciliation pass so later packs do not trigger more 429s.
            if isinstance(exc, ProviderRetryError):
                raise
    since = datetime.now(timezone.utc).timestamp() - 8 * 86400
    rows = (supabase_db.table("mercadolivre_chat_conversations").select("pack_id,seller_id,raw_json")
            .eq("marketplace_integration_id", int(integration_id)).gte("last_message_at",
              datetime.fromtimestamp(since, timezone.utc).isoformat()).order("last_synced_at").limit(limit).execute().data or [])
    synced = 0
    for row in rows:
        if (str(row["pack_id"]), str(row["seller_id"])) in scanned:
            continue
        try:
            metadata = _json(row.get("raw_json"), {}) or {}
            sync_pack(integration_id, row["pack_id"], row["seller_id"],
                      order_id_fallback=metadata.get("order_id_fallback"))
            synced += 1
        except Exception as exc:
            logger.exception("Mercado Livre reconciliation failed integration=%s pack=%s", integration_id, row.get("pack_id"))
            # Leave remaining packs for the next scheduled pass after the
            # provider's retry window instead of continuing to call the API.
            if isinstance(exc, ProviderRetryError):
                raise
    return {"reconciled": synced, "unread_recovered": unread_synced}


def reconcile_once(integration_id: int | None = None, *, limit: int = 25) -> dict:
    """Run shared inbox processing and account-scoped unread/history reconciliation."""
    accounts = message_consumer_accounts()
    if integration_id is not None:
        accounts = [account for account in accounts
                    if account["integration_id"] == int(integration_id)]
    integration_ids = [account["integration_id"] for account in accounts]
    result = process_inbox_once(integration_ids, limit=limit)
    result.update(reconciled=0, unread_recovered=0, reconcile_errors=0)
    for account_id in integration_ids:
        try:
            account_result = _reconcile_account_once(account_id, limit=limit)
            result["reconciled"] += account_result["reconciled"]
            result["unread_recovered"] += account_result["unread_recovered"]
        except Exception:
            result["reconcile_errors"] += 1
            logger.exception("Mercado Livre account reconciliation failed integration=%s", account_id)
    return result


def list_personalized_orders(integration_id: int, limit: int = 200, *,
                            pedido_ids: list[int] | None = None,
                            pack_ids: list[str] | None = None) -> list[dict]:
    _integration(integration_id, active=False)
    from nistiprint_shared.constants import STATUS_PEDIDO_PRONTO_ENVIO
    statuses = [2, STATUS_PEDIDO_PRONTO_ENVIO]
    page_size = 250
    requested = min(max(int(limit), 1), 5000)
    orders = []
    for start in range(0, requested, page_size):
        page = (supabase_db.table("pedidos").select(
            "id,numero_pedido,codigo_pedido_externo,marketplace_order_id,marketplace_integration_id,"
            "data_venda,situacao_pedido_id,cliente_nome,buyer_username,informacoes_cliente,message_to_seller"
        ).eq("marketplace_integration_id", int(integration_id)).in_("situacao_pedido_id", statuses)
          .order("data_venda", desc=True).order("id", desc=True))
        query = page
        if pedido_ids is not None:
            if not pedido_ids:
                return []
            query = query.in_("id", pedido_ids)
        page = query.range(start, min(start + page_size, requested) - 1).execute().data or []
        orders.extend(page)
        if len(page) < min(page_size, requested - start):
            break
    if not orders:
        return []
    ids = [int(order["id"]) for order in orders]
    items = (supabase_db.table("itens_pedido").select("id,pedido_id,sku_externo,descricao,titulo_anuncio,variacao_externa,quantidade,preco_unitario,personalizado")
             .in_("pedido_id", ids).order("id").execute().data or [])
    from nistiprint_shared.services.personalized_classification_service import classify_items
    items_by_order: dict[int, list] = {}
    for item in items:
        candidate = {"descricao": item.get("titulo_anuncio") or item.get("descricao")}
        item["personalizado"] = bool(item.get("personalizado")) or bool(classify_items([candidate]).matched_items)
        if not item["personalizado"]:
            continue
        items_by_order.setdefault(int(item["pedido_id"]), []).append(item)
    output = []
    conversations = (supabase_db.table("mercadolivre_chat_conversations").select(
        "pack_id,seller_id,order_ids,last_message_at,last_synced_at,context_hash,ai_status,needs_review,last_ai_executed_at,last_error,raw_json"
    ).eq("marketplace_integration_id", int(integration_id)))
    if pack_ids is not None:
        conversations = conversations.in_("pack_id", pack_ids) if pack_ids else None
    conversations = conversations.execute().data if conversations is not None else []
    conversations_by_order: dict[str, list[dict]] = {}
    for conversation in conversations:
        for linked_order_id in (_json(conversation.get("order_ids"), []) or []):
            conversations_by_order.setdefault(str(linked_order_id), []).append(conversation)

    # The list screen can request thousands of orders. Fetch chat and result rows
    # once per account instead of issuing two/three PostgREST requests per order.
    pack_ids = sorted({str(row.get("pack_id")) for row in conversations if row.get("pack_id")})
    messages = []
    for pack_offset in range(0, len(pack_ids), 100):
        pack_batch = pack_ids[pack_offset:pack_offset + 100]
        for start in range(0, 100_000, 1000):
            page = (supabase_db.table("mercadolivre_chat_messages").select(
                "pack_id,provider_message_id,sender_role,created_at,text_content,moderation_status,attachments"
            ).eq("marketplace_integration_id", int(integration_id)).in_("pack_id", pack_batch)
             .order("created_at").range(start, start + 999).execute().data or [])
            messages.extend(page)
            if len(page) < 1000:
                break
    messages_by_pack: dict[str, list[dict]] = {}
    for message in messages:
        messages_by_pack.setdefault(str(message.get("pack_id")), []).append(message)
    message_count_by_pack = {pack_id: len(pack_messages)
                             for pack_id, pack_messages in messages_by_pack.items()}
    result_rows = []
    for order_offset in range(0, len(ids), 100):
        order_batch = ids[order_offset:order_offset + 100]
        for start in range(0, 100_000, 1000):
            page = (supabase_db.table("mercadolivre_personalizations").select("*")
                    .eq("marketplace_integration_id", int(integration_id)).in_("pedido_id", order_batch)
                    .order("updated_at", desc=True).range(start, start + 999).execute().data or [])
            result_rows.extend(page)
            if len(page) < 1000:
                break
    results_by_order: dict[int, list[dict]] = {}
    for row in result_rows:
        try:
            results_by_order.setdefault(int(row.get("pedido_id")), []).append(row)
        except (TypeError, ValueError):
            continue

    for order in orders:
        order_id = int(order["id"])
        if order_id not in items_by_order:
            continue
        external = str(order.get("marketplace_order_id") or order.get("codigo_pedido_externo") or "")
        linked = conversations_by_order.get(external, [])
        conversation_messages = messages_by_pack.get(str(linked[0].get("pack_id")), []) if linked else []
        current_hash = (_context_hash(conversation_messages) if conversation_messages else
                        linked[0].get("context_hash") if linked else None)
        order_result_rows = results_by_order.get(order_id, [])
        # Keep the last completed extraction visible while newer buyer context is pending.
        valid_rows = order_result_rows
        by_item: dict[int, list[dict]] = {}
        for row in valid_rows:
            if row.get("item_pedido_id"):
                by_item.setdefault(int(row["item_pedido_id"]), []).append(row)
        # Keep every personalization from the selected execution context:
        # one item may have several distinct names. Prefer the newest context
        # that identified a name so a later inconclusive run doesn't hide it.
        for item_id, rows in by_item.items():
            contexts: dict[str, list[dict]] = {}
            for row in rows:
                contexts.setdefault(str(row.get("context_hash") or ""), []).append(row)
            identified_contexts = [context_rows for context_rows in contexts.values()
                                   if any(str(row.get("customization_name") or "").strip()
                                          or str(row.get("customization_initial") or "").strip()
                                          for row in context_rows)]
            candidates = identified_contexts or list(contexts.values())
            selected_context = max(
                candidates,
                key=lambda context_rows: max(str(row.get("updated_at") or "")
                                             for row in context_rows),
            )
            by_item[item_id] = sorted(
                selected_context,
                key=lambda row: (str(row.get("updated_at") or ""), int(row.get("id") or 0)),
            )
        message_count = 0
        messages = []
        if linked:
            message_count = message_count_by_pack.get(str(linked[0].get("pack_id")), 0)
            messages = conversation_messages
        conversation = linked[0] if linked else {}
        last_buyer_message_at = max((row.get("created_at") or "" for row in messages
                                     if row.get("sender_role") == "buyer"), default="") or None
        ai_status = conversation.get("ai_status") or next((str(row.get("status", "")).lower()
                                                             for row in valid_rows), None)
        last_ai_at = conversation.get("last_ai_executed_at")
        has_buyer_message = bool(str(order.get("message_to_seller") or "").strip()) or bool(last_buyer_message_at)
        conversation_metadata = _json(conversation.get("raw_json"), {}) or {}
        has_chat_context = bool(conversation_metadata.get("order_id_fallback")
                                or conversation_metadata.get("buyer_ids") or message_count)
        item_ids = {int(item["id"]) for item in items_by_order[order_id]}
        current_rows = [row for row in valid_rows if int(row.get("item_pedido_id") or 0) in item_ids
                        and row.get("context_hash") == current_hash]
        quantity_by_item: dict[int, int] = {}
        for row in current_rows:
            item_id = int(row["item_pedido_id"])
            quantity_by_item[item_id] = quantity_by_item.get(item_id, 0) + int(row.get("quantity_to_personalize") or 0)
        extraction_missing = bool(current_hash and any(
            quantity_by_item.get(int(item["id"]), 0) != max(1, int(item.get("quantidade") or 1))
            for item in items_by_order[order_id]
        ))
        needs_ai = bool(conversation.get("last_error")) or extraction_missing or (
            not last_ai_at and (has_chat_context or has_buyer_message)
        ) or bool(last_buyer_message_at and last_ai_at and last_buyer_message_at > last_ai_at)
        for row in valid_rows:
            row.update(_source_metadata(row))
        output.append({**order, "integration_id": int(integration_id), "external_order_id": external,
                       "pack_id": linked[0].get("pack_id") if linked else None,
                       "last_message_at": linked[0].get("last_message_at") if linked else None,
                       "has_chat_messages": message_count > 0,
                       "chat_available": bool(linked), "has_buyer_message": has_buyer_message,
                       "last_buyer_message_at": last_buyer_message_at,
                       "last_ai_executed_at": last_ai_at, "needs_ai_processing": needs_ai,
                       "ai_status": ai_status,
                       "chat_context_ambiguous": bool(linked and (linked[0].get("needs_review")
                           or any(row.get("sender_role") == "unknown" for row in conversation_messages))),
                       "items": [{**item, "personalizations": by_item.get(int(item["id"]), []),
                                  "personalization": (by_item.get(int(item["id"])) or [None])[0]}
                                 for item in items_by_order[order_id]]})
    return output


def list_personalized_order_page(integration_id: int, *, page: int = 1, page_size: int = 20,
                                 search: str = "", ai_filter: str = "",
                                 chat_filter: str = "") -> dict:
    """Return a small page assembled from indexed order-level summaries."""
    _integration(integration_id, active=False)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    base = supabase_db.table("view_mercadolivre_personalization_order_summary").select(
        "id,pack_id,needs_ai_processing,has_chat_messages,has_identified_name,has_no_name",
        count="exact",
    ).eq("marketplace_integration_id", int(integration_id))
    if search.strip():
        value = search.strip().replace("%", "\\%").replace(",", "\\,")
        base = base.or_(
            f"numero_pedido.ilike.%{value}%,codigo_pedido_externo.ilike.%{value}%,"
            f"cliente_nome.ilike.%{value}%,buyer_username.ilike.%{value}%"
        )
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
            base = base.eq(column, value)

    def count_for(**where):
        query = supabase_db.table("view_mercadolivre_personalization_order_summary").select(
            "id", count="exact", head=True
        ).eq("marketplace_integration_id", int(integration_id))
        for column, value in where.items():
            query = query.eq(column, value)
        return int(getattr(query.execute(), "count", 0) or 0)

    from concurrent.futures import ThreadPoolExecutor as _Pool
    count_specs = {
        "pendente_ia": {"needs_ai_processing": True},
        "com_chat": {"has_chat_messages": True},
        "sem_chat": {"has_chat_messages": False},
        "nome_identificado": {"has_identified_name": True},
        "sem_nome": {"has_no_name": True},
    }
    with _Pool(max_workers=5) as pool:
        count_futures = {key: pool.submit(count_for, **where) for key, where in count_specs.items()}
        response = base.order("data_venda", desc=True).order("id", desc=True).range(
            (page - 1) * page_size, page * page_size - 1
        ).execute()
        status_counts = {key: future.result() for key, future in count_futures.items()}
    summaries = response.data or []
    ids = [int(row["id"]) for row in summaries]
    packs = sorted({str(row["pack_id"]) for row in summaries if row.get("pack_id")})
    orders = list_personalized_orders(integration_id, limit=page_size, pedido_ids=ids, pack_ids=packs)
    order_by_id = {int(row["id"]): row for row in orders}
    total = int(getattr(response, "count", 0) or 0)
    return {
        "orders": [order_by_id[order_id] for order_id in ids if order_id in order_by_id],
        "pagination": {"page": page, "page_size": page_size, "total": total,
                       "has_next": page * page_size < total},
        "status_counts": status_counts,
    }


def conversation_for_order(integration_id: int, pedido_id: int) -> dict:
    orders = (supabase_db.table("pedidos").select("id,codigo_pedido_externo,marketplace_order_id")
              .eq("id", int(pedido_id)).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not orders:
        raise LookupError("Pedido não pertence à conta Mercado Livre informada")
    external = str(orders[0].get("marketplace_order_id") or orders[0].get("codigo_pedido_externo") or "")
    conversations = (supabase_db.table("mercadolivre_chat_conversations").select("*")
                     .eq("marketplace_integration_id", int(integration_id)).execute().data or [])
    conversation = next((row for row in conversations if external in
                         [str(value) for value in (_json(row.get("order_ids"), []) or [])]), None)
    if not conversation:
        return {"pedido_id": int(pedido_id), "messages": []}
    messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", conversation["pack_id"])
                .order("created_at").execute().data or [])
    return {"pedido_id": int(pedido_id), "conversation": conversation, "messages": messages}


def list_pending_conversations(integration_id: int, limit: int = 100) -> list[dict]:
    """Conversations whose provider orders have not arrived in the canonical order store yet."""
    _integration(integration_id, active=False)
    conversations = (supabase_db.table("mercadolivre_chat_conversations").select("*")
                     .eq("marketplace_integration_id", int(integration_id))
                     .order("last_message_at", desc=True).limit(min(max(int(limit), 1), 200))
                     .execute().data or [])
    external_ids = list(dict.fromkeys(str(value) for conversation in conversations
                        for value in (_json(conversation.get("order_ids"), []) or [])))
    known = set()
    for start in range(0, len(external_ids), 100):
        page = external_ids[start:start + 100]
        rows = (supabase_db.table("pedidos").select("codigo_pedido_externo,marketplace_order_id")
                .eq("marketplace_integration_id", int(integration_id))
                .in_("codigo_pedido_externo", page).execute().data or [])
        known.update(str(row.get("codigo_pedido_externo")) for row in rows if row.get("codigo_pedido_externo"))
        known.update(str(row.get("marketplace_order_id")) for row in rows if row.get("marketplace_order_id"))
        remaining = [value for value in page if value not in known]
        if remaining:
            fallback = (supabase_db.table("pedidos").select("marketplace_order_id")
                        .eq("marketplace_integration_id", int(integration_id))
                        .in_("marketplace_order_id", remaining).execute().data or [])
            known.update(str(row.get("marketplace_order_id")) for row in fallback if row.get("marketplace_order_id"))
    output = []
    for conversation in conversations:
        order_ids = [str(value) for value in (_json(conversation.get("order_ids"), []) or [])]
        if not order_ids or any(value in known for value in order_ids):
            continue
        messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                    .eq("marketplace_integration_id", int(integration_id))
                    .eq("pack_id", conversation["pack_id"]).order("created_at").execute().data or [])
        output.append({**conversation, "messages": messages,
                       "pending_order_ids": order_ids, "association_status": "awaiting_order_import"})
    return output


def list_unmatched_notifications(integration_id: int | None = None, limit: int = 100) -> list[dict]:
    """Expose identity failures for audit; never place them on a processing queue."""
    query = supabase_db.table("mercadolivre_chat_inbox").select(
        "id,marketplace_integration_id,account_user_id,application_id,provider_message_id,"
        "webhook_event_id,actions,last_error,created_at"
    ).eq("status", "unmatched")
    if integration_id is not None:
        _integration(integration_id, active=False)
        query = query.eq("marketplace_integration_id", int(integration_id))
    return query.order("created_at", desc=True).limit(min(max(int(limit), 1), 200)).execute().data or []


def account_health(integration_id: int) -> dict:
    _integration(integration_id, active=False)
    settings = _settings(integration_id)
    pending = (supabase_db.table("mercadolivre_chat_inbox").select("id", count="exact")
               .eq("marketplace_integration_id", int(integration_id))
               .in_("status", ["pending", "retry", "processing"]).execute())
    oldest = (supabase_db.table("mercadolivre_chat_inbox").select("created_at")
              .eq("marketplace_integration_id", int(integration_id))
              .in_("status", ["pending", "retry"]).order("created_at").limit(1).execute().data or [])
    failed = (supabase_db.table("mercadolivre_chat_inbox").select("id", count="exact")
              .eq("marketplace_integration_id", int(integration_id)).eq("status", "failed").execute())
    reviews = (supabase_db.table("mercadolivre_personalizations").select("id", count="exact")
               .eq("marketplace_integration_id", int(integration_id)).eq("confirmed", False)
               .eq("status", "NEEDS_REVIEW").execute())
    ai_errors = (supabase_db.table("mercadolivre_personalization_logs").select("id", count="exact")
                 .eq("marketplace_integration_id", int(integration_id)).eq("status", "error").execute())
    capture_errors = (supabase_db.table("mercadolivre_personalization_logs").select("id", count="exact")
                      .eq("marketplace_integration_id", int(integration_id))
                      .eq("status", "capture_error").execute())
    incomplete = (supabase_db.table("mercadolivre_chat_conversations").select("id", count="exact")
                  .eq("marketplace_integration_id", int(integration_id)).eq("needs_review", True).execute())
    def count(response):
        return response.count if response.count is not None else len(response.data or [])
    return {"integration_id": int(integration_id),
            "schedule_enabled": bool(settings.get("schedule_enabled", True)),
            "schedule_hour": settings.get("schedule_hour", 9),
            "schedule_minute": settings.get("schedule_minute", 0),
            "last_daily_run": settings.get("last_scheduled_run_date"),
            "inbox_pending": count(pending), "oldest_pending_at": oldest[0].get("created_at") if oldest else None,
            "inbox_failed": count(failed), "waiting_review": count(reviews),
            "incomplete_conversations": count(incomplete), "ai_errors": count(ai_errors),
            "capture_errors": count(capture_errors)}


def _integration_orders(integration_id: int, external_order_ids: list[str]) -> list[dict]:
    if not external_order_ids:
        return []
    rows = (supabase_db.table("pedidos").select("id,numero_pedido,codigo_pedido_externo,marketplace_order_id,data_venda,situacao_pedido_id,cliente_nome,message_to_seller")
            .eq("marketplace_integration_id", int(integration_id)).in_("codigo_pedido_externo", external_order_ids).execute().data or [])
    # Some direct-import builds store marketplace_order_id as the external key.
    existing = {str(row.get("codigo_pedido_externo")) for row in rows}
    missing = [value for value in external_order_ids if value not in existing]
    if missing:
        rows.extend(supabase_db.table("pedidos").select("id,numero_pedido,codigo_pedido_externo,marketplace_order_id,data_venda,situacao_pedido_id,cliente_nome,message_to_seller")
                    .eq("marketplace_integration_id", int(integration_id)).in_("marketplace_order_id", missing).execute().data or [])
    return rows


def _pack_context(integration_id: int, pack_id: str, *, include_messages: bool = False,
                  conversation: dict | None = None):
    conversations = [conversation] if conversation else (
        supabase_db.table("mercadolivre_chat_conversations").select("*")
        .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
        .limit(1).execute().data or []
    )
    if not conversations:
        raise LookupError("Conversa Mercado Livre ainda não sincronizada")
    conversation = conversations[0]
    external_ids = [str(value) for value in (_json(conversation.get("order_ids"), []) or [])]
    orders = _integration_orders(integration_id, external_ids)
    if not orders:
        raise LookupError("Aguardando importação dos pedidos relacionados ao pacote")
    order_ids = [int(order["id"]) for order in orders]
    items = (supabase_db.table("itens_pedido").select("id,pedido_id,sku_externo,descricao,titulo_anuncio,variacao_externa,quantidade,personalizado")
             .in_("pedido_id", order_ids).execute().data or [])
    from nistiprint_shared.services.personalized_classification_service import classify_items
    items = [item for item in items if item.get("personalizado") or classify_items([{
        "descricao": item.get("titulo_anuncio") or item.get("descricao")
    }]).matched_items]
    messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id)).order("created_at").execute().data or [])
    digest = _context_hash(messages)
    flags = any(message.get("sender_role") == "unknown"
                or (message.get("attachments") and not _text(message.get("text_content")))
                or message.get("moderation_status") not in {None, "", "available"}
                for message in messages)
    if include_messages:
        return orders, items, digest, flags, messages
    return orders, items, digest, flags


def _ai_response(integration_id: int, settings: dict, system_prompt: str, payload: str):
    from nistiprint_shared.services.ai import extract_json
    from nistiprint_shared.services.ai.base import AIProviderError
    from nistiprint_shared.services.ai.gemini_provider import GeminiProvider
    from nistiprint_shared.services.ai.openrouter_provider import OpenRouterProvider

    suffix = str(int(integration_id))
    keys = {
        "gemini": (os.getenv(f"MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY_{suffix}")
                   or os.getenv("MERCADOLIVRE_PERSONALIZACAO_GEMINI_API_KEY")),
        "openrouter": (os.getenv(f"MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY_{suffix}")
                       or os.getenv("MERCADOLIVRE_PERSONALIZACAO_OPENROUTER_API_KEY")),
    }
    provider_name = str(settings.get("provider") or "gemini")
    timeout = max(1, min(600, int(settings.get("timeout_seconds") or 60)))
    provider = (GeminiProvider(model=settings.get("model_name"), api_key=keys["gemini"], timeout=timeout)
                if provider_name == "gemini" else
                OpenRouterProvider(model=settings.get("model_name"), api_key=keys["openrouter"],
                                   timeout=float(settings.get("timeout_seconds") or 60)))
    try:
        response = provider.complete(system_prompt, payload, response_schema=PERSONALIZATION_RESPONSE_SCHEMA)
    except AIProviderError:
        fallback_name = settings.get("fallback_provider")
        if not fallback_name or not keys.get(fallback_name):
            raise
        fallback_model = "gemini-2.5-flash" if fallback_name == "gemini" else "openrouter/auto"
        fallback = (GeminiProvider(model=fallback_model, api_key=keys["gemini"], timeout=timeout)
                    if fallback_name == "gemini" else
                    OpenRouterProvider(model=fallback_model, api_key=keys["openrouter"],
                                      timeout=float(settings.get("timeout_seconds") or 60)))
        response = fallback.complete(system_prompt, payload, response_schema=PERSONALIZATION_RESPONSE_SCHEMA)
    return extract_json(response.text), response


def _has_current_extraction(integration_id: int, pack_id: str, digest: str,
                            items: list[dict]) -> bool:
    rows = (supabase_db.table("mercadolivre_personalizations").select(
        "item_pedido_id,quantity_to_personalize,status,context_hash"
    ).eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
      .eq("context_hash", digest).execute().data or [])
    quantity_by_item: dict[int, int] = {}
    for row in rows:
        item_id = int(row.get("item_pedido_id") or 0)
        quantity_by_item[item_id] = quantity_by_item.get(item_id, 0) + int(row.get("quantity_to_personalize") or 0)
    return all(
        quantity_by_item.get(int(item["id"]), 0) == max(1, int(item.get("quantidade") or 1))
        for item in items
    )


def process_pack(integration_id: int, pack_id: str, *, batch_id: str | None = None,
                 force: bool = False, settings: dict | None = None,
                 run_token: str | None = None) -> dict:
    _integration(integration_id)
    settings = settings or _settings(integration_id)
    conversation_rows = (supabase_db.table("mercadolivre_chat_conversations").select(
        "seller_id,raw_json,context_hash,current_context_hash,ai_status"
    )
                         .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
                         .limit(1).execute().data or [])
    if not conversation_rows:
        raise LookupError("Conversa Mercado Livre ainda não sincronizada")
    # Message capture is owned by the inbox/reconciliation tasks. AI consumes
    # only the persisted account-scoped snapshot and never calls the provider.
    context = _pack_context(
        integration_id, pack_id, include_messages=True, conversation=conversation_rows[0],
    )
    if len(context) == 4:  # compatibility with callers/tests mocking the old context shape
        orders, items, digest, forced_review = context
        messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                    .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id))
                    .order("created_at", desc=False).execute().data or [])
    else:
        orders, items, digest, forced_review, messages = context
    conversation = conversation_rows[0]
    if (not force and (conversation.get("current_context_hash") or conversation.get("context_hash")) == digest
            and conversation.get("ai_status") == "success"
            and _has_current_extraction(integration_id, pack_id, digest, items)):
        return {"status": "up_to_date", "pack_id": str(pack_id)}
    if not items:
        raise LookupError("Pacote sem itens personalizados elegíveis")
    if run_token and batch_id:
        _assert_batch_run(integration_id, batch_id, run_token)
    payload_obj = {"pack_id": str(pack_id), "orders": [{"pedido_id": order["id"],
                    "external_order_id": order.get("marketplace_order_id") or order.get("codigo_pedido_externo"),
                    "message_to_seller": order.get("message_to_seller") or "",
                    "items": [{"item_id": item["id"], "description": item.get("titulo_anuncio") or item.get("descricao"),
                               "quantity": item.get("quantidade", 1)} for item in items if int(item["pedido_id"]) == int(order["id"])]}
                    for order in orders],
                    "messages": [{"id": message.get("provider_message_id"), "sender_role": message.get("sender_role"),
                                  "created_at": message.get("created_at"), "text": message.get("text_content"),
                                  "attachments": message.get("attachments") or []} for message in messages]}
    user_payload = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    prompt = (str(settings.get("prompt_template") or DEFAULT_PROMPT).strip()
              + "\n\nContrato obrigatório: retorne exatamente um objeto conforme o schema JSON da chamada."
              " Inclua todos os itens; use os IDs internos recebidos; não invente campos nem fontes;"
              " todos os itens sem personalização também devem aparecer com campos nulos.")
    response = None
    try:
        result, response = _ai_response(integration_id, settings, prompt, user_payload)
        if not isinstance(result, dict):
            raise ValueError("Resposta da IA precisa ser um objeto JSON")
        status = str(result.get("status") or "").upper()
        if status not in {"SUCCESS", "NEEDS_REVIEW", "NO_PERSONALIZATION_FOUND"}:
            raise ValueError("Resposta da IA contém status inválido")
        entries = result.get("personalized_items")
        if not isinstance(entries, list):
            raise ValueError("Resposta da IA não contém personalized_items em formato de lista")
        if not isinstance(result.get("reasoning"), str):
            raise ValueError("Resposta da IA não contém reasoning em formato de texto")
        item_map = {str(item["id"]): item for item in items}
        valid_message_ids = {str(message.get("provider_message_id")) for message in messages if message.get("sender_role") == "buyer"}
        order_by_id = {int(order["id"]): order for order in orders}
        records = []
        seen: dict[int, int] = {}
        personalized_quantity: dict[int, int] = {}
        names_found = False
        for entry in entries:
            required_fields = {"item_id", "quantity_to_personalize", "customization_name",
                               "name_source_message_id", "customization_initial", "initial_source_message_id"}
            if not isinstance(entry, dict) or set(entry) != required_fields:
                raise ValueError("Linha da IA não corresponde ao schema de personalização")
            raw_item_id = entry.get("item_id")
            if isinstance(raw_item_id, bool) or not isinstance(raw_item_id, int):
                raise ValueError("item_id da IA precisa ser um ID interno inteiro")
            item = item_map.get(str(raw_item_id))
            item_order = order_by_id.get(int(item["pedido_id"])) if item else None
            source_id = str(entry.get("name_source_message_id") or "")
            initial_source_id = str(entry.get("initial_source_message_id") or "")
            valid_name_source = (source_id in valid_message_ids or
                                 source_id == "message_to_seller" and bool(
                                     _text((item_order or {}).get("message_to_seller"))))
            valid_initial_source = (initial_source_id in valid_message_ids or
                                    initial_source_id == "message_to_seller" and bool(
                                        _text((item_order or {}).get("message_to_seller"))))
            raw_quantity = entry.get("quantity_to_personalize")
            if isinstance(raw_quantity, bool) or not isinstance(raw_quantity, int):
                raise ValueError("quantity_to_personalize da IA precisa ser inteiro")
            quantity = raw_quantity
            name = entry.get("customization_name")
            initial = entry.get("customization_initial")
            if (name is not None and not isinstance(name, str)) or (initial is not None and not isinstance(initial, str)):
                raise ValueError("Nome e inicial da IA precisam ser texto ou nulos")
            if (entry.get("name_source_message_id") is not None and not isinstance(entry.get("name_source_message_id"), str)
                    or entry.get("initial_source_message_id") is not None
                    and not isinstance(entry.get("initial_source_message_id"), str)):
                raise ValueError("Fontes de personalização precisam ser texto ou nulas")
            if ((entry.get("name_source_message_id") is not None
                 and not valid_name_source)
                    or (entry.get("initial_source_message_id") is not None
                        and not valid_initial_source)):
                raise ValueError("Resposta da IA referencia uma mensagem inexistente")
            if (not item or not 1 <= quantity <= max(1, int(item.get("quantidade") or 1))
                    or (name and not valid_name_source)
                    or (initial and not valid_initial_source)
                    or (name and not source_id) or (initial and not initial_source_id)):
                raise ValueError("Resposta da IA contém item, quantidade ou fonte inválida")
            names_found = names_found or bool(_text(name) or _text(initial))
            seen[item["id"]] = seen.get(item["id"], 0) + 1
            personalized_quantity[item["id"]] = personalized_quantity.get(item["id"], 0) + quantity
            if personalized_quantity[item["id"]] > max(1, int(item.get("quantidade") or 1)):
                raise ValueError("A soma das quantidades personalizadas excede o item")
            message_id = (source_id if source_id in valid_message_ids else
                          initial_source_id if initial_source_id in valid_message_ids else None)
            provider_item_base = _text(entry.get("provider_item_id")) or f"local-item-{item['id']}"
            provider_item_id = (f"{provider_item_base}#{seen[item['id']]}"
                                if seen[item["id"]] > 1 else provider_item_base)
            records.append({"marketplace_integration_id": int(integration_id),
                "pedido_id": int(item["pedido_id"]), "item_pedido_id": int(item["id"]),
                "pack_id": str(pack_id),
                "provider_order_id": str(next((o.get("marketplace_order_id") or o.get("codigo_pedido_externo") for o in orders if int(o["id"]) == int(item["pedido_id"])), "")),
                "provider_item_id": provider_item_id,
                "provider_message_id": message_id,
                "quantity_to_personalize": quantity,
                "customization_name": _text(name) or None,
                "customization_initial": _text(initial) or None,
                "status": status, "reasoning": _text(result.get("reasoning"))[:1500],
                "context_hash": digest, "source": "ai", "confirmed": False,
                "details": {"name_source_message_id": source_id or None,
                            "initial_source_message_id": initial_source_id or None}})
        if set(seen) != {int(item["id"]) for item in items}:
            raise ValueError("A resposta da IA precisa incluir cada item personalizado elegível")
        for item in items:
            if personalized_quantity.get(item["id"], 0) not in (0, max(1, int(item.get("quantidade") or 1))):
                raise ValueError("A soma das quantidades personalizadas diverge do item")
        if status == "SUCCESS" and not names_found:
            raise ValueError("A IA retornou SUCCESS sem nome nem inicial identificados")
        if status == "NO_PERSONALIZATION_FOUND" and names_found:
            raise ValueError("A IA retornou NO_PERSONALIZATION_FOUND apesar de identificar nomes")
        if {int(record["item_pedido_id"]) for record in records} != {int(item["id"]) for item in items}:
            raise ValueError("A resposta da IA não cobriu todos os itens personalizados")
        if status == "NEEDS_REVIEW":
            for record in records:
                record["status"] = status
        if forced_review:
            status = "NEEDS_REVIEW"
            for record in records:
                record["status"] = status
        if status != "SUCCESS":
            for record in records:
                record["status"] = status
        log = {"marketplace_integration_id": int(integration_id), "pack_id": str(pack_id),
               "status": "success", "input_data": user_payload[:25000],
               "model_result": result, "metadata": response.to_metadata() if response else {},
               "pedido_ids": sorted({int(order["id"]) for order in orders})}
        # SQL RPC validates account/order/item ownership and writes results + log atomically.
        if run_token and batch_id:
            _assert_batch_run(integration_id, batch_id, run_token)
        persisted = supabase_db.rpc("persist_mercadolivre_personalization_results", {
            "p_integration_id": int(integration_id), "p_pack_id": str(pack_id),
            "p_context_hash": digest, "p_status": status,
            "p_needs_review": bool(forced_review or status == "NEEDS_REVIEW"),
            "p_records": records, "p_log": log, "p_batch_id": batch_id,
        }).execute()
        confirmation = getattr(persisted, "data", None)
        if isinstance(confirmation, list):
            confirmation = confirmation[0] if confirmation else None
        if (not isinstance(confirmation, dict) or int(confirmation.get("saved", -1)) != len(records)
                or str(confirmation.get("status") or "").upper() != status):
            raise RuntimeError("Banco não confirmou a persistência integral dos resultados da IA")
        return {"status": status.lower(), "pack_id": str(pack_id), "personalizations": len(records)}
    except Exception as exc:
        if run_token and batch_id:
            _assert_batch_run(integration_id, batch_id, run_token)
        for pedido_id in sorted({int(order["id"]) for order in orders}):
            supabase_db.table("mercadolivre_personalization_logs").insert({
                "marketplace_integration_id": int(integration_id), "batch_id": batch_id,
                "pedido_id": pedido_id, "pack_id": str(pack_id), "status": "error",
                "input_data": user_payload[:25000], "error_message": str(exc)[:1000],
            }).execute()
        supabase_db.table("mercadolivre_chat_conversations").update({
            "ai_status": "error", "last_error": str(exc)[:1000], "needs_review": True,
        }).eq("marketplace_integration_id", int(integration_id)).eq("pack_id", str(pack_id)).execute()
        raise


def _queue_packs(integration_id: int, *, limit: int = 50, pedido_ids: list[int] | None = None,
                 force: bool = False) -> dict:
    query = (supabase_db.table("view_mercadolivre_personalization_order_summary")
             .select("id,pack_id").eq("marketplace_integration_id", int(integration_id))
             .order("data_venda", desc=True).order("id", desc=True))
    if not force:
        query = query.eq("needs_ai_processing", True)
    if pedido_ids:
        query = query.in_("id", [int(value) for value in pedido_ids])
    candidates = []
    offset = 0
    while len(candidates) < min(max(1, int(limit)), 500):
        page = query.range(offset, offset + 499).execute().data or []
        candidates.extend(page)
        if len(page) < 500:
            break
        offset += 500
    pack_ids = list(dict.fromkeys(str(order["pack_id"]) for order in candidates if order.get("pack_id")))[:limit]
    if not pack_ids:
        return {"batch_id": None, "total": 0, "pack_ids": [], "message": "Nenhum pacote Mercado Livre pronto para extração."}
    batch = (supabase_db.table("mercadolivre_personalization_batches").insert({
        "marketplace_integration_id": int(integration_id), "pack_ids": pack_ids,
        "total": len(pack_ids), "force": bool(force), "status": "PENDING",
    }).execute().data or [])
    if not batch:
        raise RuntimeError("Falha ao registrar o lote Mercado Livre")
    supabase_db.table("mercadolivre_personalization_batch_items").insert([
        {"batch_id": batch[0]["id"], "marketplace_integration_id": int(integration_id),
         "pack_id": pack_id, "status": "PENDING"} for pack_id in pack_ids
    ]).execute()
    return {"batch_id": batch[0]["id"], "total": len(pack_ids), "pack_ids": pack_ids,
            "message": f"{len(pack_ids)} pacote(s) enfileirado(s)."}


def queue_manual(integration_id: int, *, pedido_ids: list[int] | None = None,
                 force: bool = False, limit: int = 50, created_by: int | None = None) -> dict:
    _integration(integration_id)
    result = _queue_packs(integration_id, limit=limit, pedido_ids=pedido_ids, force=force)
    if result.get("batch_id") and created_by:
        supabase_db.table("mercadolivre_personalization_batches").update({
            "created_by": int(created_by),
        }).eq("id", result["batch_id"]).execute()
    return result


def _assert_batch_run(integration_id: int, batch_id: str, run_token: str) -> None:
    row = (supabase_db.table("mercadolivre_personalization_batches").select("id")
           .eq("id", str(batch_id)).eq("marketplace_integration_id", int(integration_id))
           .eq("status", "RUNNING").eq("run_token", str(run_token)).limit(1).execute().data or [])
    if not row:
        raise RuntimeError("Execução do lote perdeu a concessão; resultado descartado")


def _sync_batch_operation(batch: dict) -> None:
    owner_id = batch.get("created_by")
    if not owner_id:
        return
    from nistiprint_shared.database.supabase_db_service import supabase_db
    from nistiprint_shared.services.async_operation_service import async_operation_service
    batch_id = str(batch["id"])
    operation = async_operation_service.find_by_source("mercadolivre_personalization_batch", batch_id)
    raw_status = batch.get("status")
    retrying = raw_status == "FAILED" and int(batch.get("attempts") or 0) < 3
    waiting_retry = raw_status == "PENDING" and int(batch.get("attempts") or 0) > 0
    status = ("EM_ANDAMENTO" if retrying or waiting_retry else
              {"PENDING": "AGUARDANDO", "RUNNING": "EM_ANDAMENTO",
               "COMPLETED": "CONCLUIDO", "FAILED": "ERRO"}.get(raw_status, "AGUARDANDO"))
    processed, total = int(batch.get("processed") or 0), int(batch.get("total") or 0)
    items = (supabase_db.table("mercadolivre_personalization_batch_items").select("status")
             .eq("batch_id", batch_id).execute().data or [])
    failed = sum(row.get("status") == "FAILED" for row in items)
    success = sum(row.get("status") == "COMPLETED" for row in items)
    values = {
        "mensagem": (f"{processed} de {total} pacotes processados; nova tentativa agendada"
                     if retrying else f"{processed} de {total} pacotes processados"),
        "status": status,
        "etapa": {"AGUARDANDO": "Na fila", "EM_ANDAMENTO": "Processando personalizações",
                  "CONCLUIDO": "Concluído", "ERRO": "Falhou"}[status],
        "progresso_atual": processed, "progresso_total": total,
        "erro_resumo": f"{failed} pacote(s) com falha" if failed else None,
        "dados_adicionais": {"sucesso": success, "falha": failed,
                             "marketplace": "mercadolivre",
                             "integration_id": batch["marketplace_integration_id"]},
        "rota_destino": f"/vendas/personalizadas/mercadolivre/{batch['marketplace_integration_id']}",
    }
    if operation:
        async_operation_service.update_operation(operation["id"], **values)
    else:
        created = async_operation_service.create_operation(
            owner_user_id=int(owner_id), categoria="IA",
            titulo="Personalizações do Mercado Livre",
            mensagem=values["mensagem"], referencia_tipo="mercadolivre_personalization_batch",
            referencia_id=batch_id, rota_destino=values["rota_destino"],
            progresso_total=total, origem_tipo="mercadolivre_personalization_batch",
            origem_id=batch_id, dados_adicionais=values["dados_adicionais"],
        )
        if status != "AGUARDANDO":
            async_operation_service.update_operation(created["id"], **values)


def _renew_batch_lease(integration_id: int, batch_id: str, run_token: str,
                      stopped: threading.Event) -> None:
    while not stopped.wait(30):
        try:
            supabase_db.table("mercadolivre_personalization_batches").update({
                "lease_until": datetime.fromtimestamp(time.time() + 300, timezone.utc).isoformat(),
            }).eq("id", str(batch_id)).eq("marketplace_integration_id", int(integration_id))\
              .eq("status", "RUNNING").eq("run_token", str(run_token)).execute()
        except Exception:
            logger.exception("Could not renew Mercado Livre AI batch lease batch=%s", batch_id)


def _iter_pack_results(integration_id: int, batch_id: str, items: list[dict],
                       force: bool, settings: dict, run_token: str):
    """Run up to ten account-scoped AI calls and yield as slots complete."""
    with ThreadPoolExecutor(max_workers=10, thread_name_prefix=f"ml-ai-{integration_id}") as executor:
        futures = {
            executor.submit(process_pack, integration_id, str(item["pack_id"]),
                            batch_id=str(batch_id), force=force,
                            settings=settings, run_token=run_token): item
            for item in items
        }
        for future in as_completed(futures):
            try:
                yield futures[future], future.result(), None
            except Exception as exc:
                yield futures[future], None, exc


def process_batch(integration_id: int, batch_id: str) -> dict:
    rows = (supabase_db.table("mercadolivre_personalization_batches").select("*")
            .eq("id", batch_id).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not rows:
        raise LookupError("Lote não encontrado nesta conta")
    batch = rows[0]
    if batch.get("status") == "COMPLETED":
        return {"status": "completed", "processed": batch.get("processed", 0)}
    if batch.get("status") == "FAILED" and int(batch.get("attempts") or 0) >= 3:
        return {"status": "failed", "processed": batch.get("processed", 0)}
    run_token = str(uuid.uuid4())
    try:
        claim = (supabase_db.table("mercadolivre_personalization_batches").update({
            "status": "RUNNING", "started_at": _now(), "run_token": run_token,
            "attempts": int(batch.get("attempts") or 0) + 1,
            "lease_until": datetime.fromtimestamp(time.time() + 300, timezone.utc).isoformat(),
        }).eq("id", batch_id).eq("marketplace_integration_id", int(integration_id))
          .eq("status", "PENDING").execute().data or [])
    except Exception as exc:
        # The partial unique index is the cross-worker/account lock.
        if "uq_ml_personalization_one_running_batch_per_account" in str(exc):
            return {"status": "waiting_for_account_slot", "processed": batch.get("processed", 0)}
        raise
    if not claim:
        return {"status": batch.get("status", "PENDING"), "processed": batch.get("processed", 0)}
    batch = {**batch, **claim[0]}
    _sync_batch_operation(batch)
    stopped = threading.Event()
    heartbeat = threading.Thread(target=_renew_batch_lease,
        args=(integration_id, batch_id, run_token, stopped), daemon=True,
        name=f"ml-ai-lease-{integration_id}")
    heartbeat.start()
    try:
        supabase_db.table("mercadolivre_personalization_batch_items").update({
            "status": "PENDING", "error_message": "Retomada após expiração da execução anterior.",
        }).eq("batch_id", str(batch_id)).eq("status", "RUNNING").execute()
        successful_logs = (supabase_db.table("mercadolivre_personalization_logs").select("pack_id")
                           .eq("marketplace_integration_id", int(integration_id))
                           .eq("batch_id", str(batch_id)).eq("status", "success")
                           .execute().data or [])
        if successful_logs:
            supabase_db.table("mercadolivre_personalization_batch_items").upsert([
                {"batch_id": str(batch_id), "marketplace_integration_id": int(integration_id),
                 "pack_id": str(row["pack_id"]), "status": "COMPLETED", "error_message": None,
                 "finished_at": _now(), "updated_at": _now()}
                for row in successful_logs if row.get("pack_id")
            ], on_conflict="batch_id,pack_id").execute()
        items = (supabase_db.table("mercadolivre_personalization_batch_items").select("*")
                 .eq("batch_id", str(batch_id)).in_("status", ["PENDING", "FAILED"])
                 .order("pack_id").execute().data or [])
        # Recover batches created before the per-pack ledger migration.
        if not items:
            existing = (supabase_db.table("mercadolivre_personalization_batch_items").select("pack_id")
                        .eq("batch_id", str(batch_id)).execute().data or [])
            if not existing:
                items = [{"pack_id": str(pack)} for pack in (_json(batch.get("pack_ids"), []) or [])]
                supabase_db.table("mercadolivre_personalization_batch_items").upsert([
                    {"batch_id": str(batch_id), "marketplace_integration_id": int(integration_id),
                     "pack_id": item["pack_id"], "status": "PENDING"} for item in items
                ], on_conflict="batch_id,pack_id").execute()
        settings = _settings(integration_id)
        results = []
        for item, result, failure in _iter_pack_results(
            integration_id, str(batch_id), items, bool(batch.get("force")), settings, run_token,
        ):
                pack_id = str(item["pack_id"])
                status = "FAILED" if failure else "COMPLETED"
                error = str(failure)[:500] if failure else None
                _assert_batch_run(integration_id, batch_id, run_token)
                supabase_db.table("mercadolivre_personalization_batch_items").upsert({
                    "batch_id": str(batch_id), "marketplace_integration_id": int(integration_id),
                    "pack_id": pack_id, "status": status, "attempts": int(item.get("attempts") or 0) + 1,
                    "error_message": error, "finished_at": _now(), "updated_at": _now(),
                }, on_conflict="batch_id,pack_id").execute()
                results.append({"pack_id": pack_id, "status": status, "error": error,
                                "retry_after": getattr(failure, "retry_after", None) if failure else None})
                totals = (supabase_db.table("mercadolivre_personalization_batch_items")
                          .select("status").eq("batch_id", str(batch_id)).execute().data or [])
                processed = sum(row.get("status") == "COMPLETED" for row in totals)
                supabase_db.table("mercadolivre_personalization_batches").update({
                    "processed": processed,
                    "lease_until": datetime.fromtimestamp(time.time() + 300, timezone.utc).isoformat(),
                }).eq("id", str(batch_id)).eq("run_token", run_token).eq("status", "RUNNING").execute()
                _sync_batch_operation({**batch, "processed": processed, "status": "RUNNING"})

        failures = [row for row in results if row["status"] == "FAILED"]
        final = "FAILED" if failures else "COMPLETED"
        retry_delays = [float(row["retry_after"]) for row in failures if row.get("retry_after") is not None]
        terminal = (supabase_db.table("mercadolivre_personalization_batches").update({
            "status": final, "processed": sum(row["status"] == "COMPLETED" for row in
                (supabase_db.table("mercadolivre_personalization_batch_items").select("status")
                 .eq("batch_id", str(batch_id)).execute().data or [])),
            "finished_at": _now(), "lease_until": None, "run_token": None,
            "available_at": datetime.fromtimestamp(
                time.time() + min(3600, max([30.0, *retry_delays])), timezone.utc).isoformat()
                if failures else _now(),
            "error_message": json.dumps(failures, ensure_ascii=False)[:2000] if failures else None,
        }).eq("id", str(batch_id)).eq("run_token", run_token).eq("status", "RUNNING").execute().data or [])
        if terminal:
            _sync_batch_operation({**batch, **terminal[0]})
        return {"status": final.lower(), "processed": terminal[0].get("processed", 0) if terminal else batch.get("processed", 0),
                "failures": failures}
    except Exception:
        supabase_db.table("mercadolivre_personalization_batches").update({
            "status": "PENDING", "lease_until": None, "run_token": None,
        }).eq("id", str(batch_id)).eq("run_token", run_token).eq("status", "RUNNING").execute()
        raise
    finally:
        stopped.set()
        heartbeat.join(timeout=1)


def recover_batches(integration_id: int, *, limit: int = 20) -> dict:
    cutoff = datetime.fromtimestamp(time.time() - 300, timezone.utc).isoformat()
    now = _now()
    stale = (supabase_db.table("mercadolivre_personalization_batches").select("id,status")
             .eq("marketplace_integration_id", int(integration_id)).eq("status", "PENDING")
             .lt("created_at", cutoff).limit(limit).execute().data or [])
    # A running batch is only recoverable after its per-account lease expires.
    expired = (supabase_db.table("mercadolivre_personalization_batches").select("id,status")
               .eq("marketplace_integration_id", int(integration_id)).eq("status", "RUNNING")
               .lt("lease_until", now).limit(limit).execute().data or [])
    failed = (supabase_db.table("mercadolivre_personalization_batches").select("id,status")
              .eq("marketplace_integration_id", int(integration_id)).eq("status", "FAILED")
              .lt("attempts", 3).lte("available_at", now).limit(limit).execute().data or [])
    stale = list({row["id"]: row for row in [*stale, *expired, *failed]}.values())
    for batch in stale:
        if batch["status"] in {"RUNNING", "FAILED"}:
            status = batch["status"]
            if status == "RUNNING":
                reset = (supabase_db.table("mercadolivre_personalization_batches").update({
                    "status": "PENDING", "lease_until": None, "finished_at": None,
                    "error_message": "Lote retomado após expiração da execução anterior.",
                }).eq("id", batch["id"]).eq("marketplace_integration_id", int(integration_id))
                  .eq("status", "RUNNING").lt("lease_until", now).execute().data or [])
            else:
                reset = (supabase_db.table("mercadolivre_personalization_batches").update({
                    "status": "PENDING", "finished_at": None,
                }).eq("id", batch["id"]).eq("marketplace_integration_id", int(integration_id))
                  .eq("status", "FAILED").lt("attempts", 3).lte("available_at", now).execute().data or [])
            if not reset:
                continue
        process_batch(integration_id, batch["id"])
    return {"recovered": len(stale)}


def batch_status(integration_id: int, batch_id: str) -> dict:
    rows = (supabase_db.table("mercadolivre_personalization_batches").select("*")
            .eq("id", batch_id).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not rows:
        raise LookupError("Lote não encontrado nesta conta")
    batch = rows[0]
    items = (supabase_db.table("mercadolivre_personalization_batch_items").select("status")
             .eq("batch_id", str(batch_id)).execute().data or [])
    batch["sucesso"] = sum(row.get("status") == "COMPLETED" for row in items)
    batch["falha"] = sum(row.get("status") == "FAILED" for row in items)
    terminal = batch.get("status") in {"COMPLETED", "FAILED"}
    return batch


def logs_for_order(integration_id: int, pedido_id: int) -> list[dict]:
    owned = (supabase_db.table("pedidos").select("id").eq("id", int(pedido_id))
             .eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not owned:
        raise LookupError("Pedido não pertence à conta informada")
    return (supabase_db.table("mercadolivre_personalization_logs").select("*")
            .eq("marketplace_integration_id", int(integration_id)).eq("pedido_id", int(pedido_id))
            .order("executed_at", desc=True).limit(100).execute().data or [])


def delete_logs_for_order(integration_id: int, pedido_id: int) -> int:
    owned = (supabase_db.table("pedidos").select("id").eq("id", int(pedido_id))
             .eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not owned:
        raise LookupError("Pedido não pertence à conta informada")
    deleted = (supabase_db.table("mercadolivre_personalization_logs").delete()
               .eq("marketplace_integration_id", int(integration_id)).eq("pedido_id", int(pedido_id))
               .execute().data or [])
    return len(deleted)


def save_order_feedback(integration_id: int, pedido_id: int, notes: str, *, user_id: int | None = None) -> dict:
    order = (supabase_db.table("pedidos").select("id,codigo_pedido_externo,marketplace_order_id")
             .eq("id", int(pedido_id)).eq("marketplace_integration_id", int(integration_id))
             .limit(1).execute().data or [])
    if not order:
        raise LookupError("Pedido não pertence à conta informada")
    text = str(notes or "").strip()
    if not text:
        raise ValueError("Descreva o problema encontrado")
    return (supabase_db.table("feedback_pedido").insert({
        "codigo_pedido": str(order[0].get("marketplace_order_id") or order[0].get("codigo_pedido_externo") or ""),
        "avaliacao": 1, "texto_feedback": text[:5000],
        "marketplace_integration_id": int(integration_id), "pedido_id": int(pedido_id),
    }).execute().data or [{}])[0]


def confirm_personalization(integration_id: int, personalization_id: int, body: dict,
                           *, user_id: int | None = None) -> dict:
    rows = (supabase_db.table("mercadolivre_personalizations").select("*")
            .eq("id", int(personalization_id)).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not rows:
        raise LookupError("Personalização não encontrada nesta conta")
    record = rows[0]
    order = (supabase_db.table("pedidos").select("id,marketplace_integration_id")
             .eq("id", record["pedido_id"]).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    item = (supabase_db.table("itens_pedido").select("id,pedido_id,quantidade")
            .eq("id", record["item_pedido_id"]).eq("pedido_id", record["pedido_id"]).limit(1).execute().data or [])
    if not order or not item:
        raise LookupError("Pedido ou item não pertence à conta informada")
    name = _text(body.get("customization_name")) or None
    initial = _text(body.get("customization_initial")) or None
    if not name and not initial:
        raise ValueError("Informe um nome ou uma inicial para confirmar")
    try:
        quantity = int(body.get("quantity_to_personalize") or record.get("quantity_to_personalize") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantidade inválida") from exc
    if not 1 <= quantity <= max(1, int(item[0].get("quantidade") or 1)):
        raise ValueError("Quantidade incompatível com o item")
    messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                .eq("marketplace_integration_id", int(integration_id))
                .eq("pack_id", record["pack_id"]).order("created_at").execute().data or [])
    current_hash = _context_hash(messages) if messages else record["context_hash"]
    updated = (supabase_db.table("mercadolivre_personalizations").update({
        "customization_name": name, "customization_initial": initial,
        "quantity_to_personalize": quantity, "status": "SUCCESS", "source": "manual",
        "context_hash": current_hash, "confirmed": True, "confirmed_by": user_id,
        "confirmed_at": _now(), "updated_at": _now(),
    }).eq("id", int(personalization_id)).eq("marketplace_integration_id", int(integration_id)).execute().data or [])
    supabase_db.table("mercadolivre_chat_conversations").update({
        "context_hash": current_hash, "ai_status": "manual_reviewed", "updated_at": _now(),
    }).eq("marketplace_integration_id", int(integration_id)).eq("pack_id", record["pack_id"]).execute()
    supabase_db.table("mercadolivre_personalization_logs").insert({
        "marketplace_integration_id": int(integration_id), "pack_id": record["pack_id"],
        "pedido_id": int(record["pedido_id"]), "status": "manual_confirmation",
        "model_result": {"personalization_id": int(personalization_id),
                         "customization_name": name, "customization_initial": initial,
                         "quantity_to_personalize": quantity},
        "metadata": {"confirmed_by": user_id},
    }).execute()
    return updated[0] if updated else {**record, "confirmed": True, "customization_name": name}


def save_manual_personalization(integration_id: int, pedido_id: int, body: dict,
                               *, user_id: int | None = None) -> dict:
    owned = (supabase_db.table("pedidos").select("id,codigo_pedido_externo,marketplace_order_id")
             .eq("id", int(pedido_id)).eq("marketplace_integration_id", int(integration_id)).limit(1).execute().data or [])
    if not owned:
        raise LookupError("Pedido não pertence à conta Mercado Livre informada")
    try:
        item_id = int(body.get("item_pedido_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("item_pedido_id é obrigatório") from exc
    items = (supabase_db.table("itens_pedido").select("id,pedido_id,quantidade,personalizado")
             .eq("id", item_id).eq("pedido_id", int(pedido_id)).limit(1).execute().data or [])
    if not items or not items[0].get("personalizado"):
        raise LookupError("Item personalizado não pertence ao pedido")
    name, initial = _text(body.get("customization_name")) or None, _text(body.get("customization_initial")) or None
    if not name and not initial:
        raise ValueError("Informe um nome ou uma inicial para salvar")
    try:
        quantity = int(body.get("quantity_to_personalize") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantidade inválida") from exc
    if not 1 <= quantity <= max(1, int(items[0].get("quantidade") or 1)):
        raise ValueError("Quantidade incompatível com o item")
    external = str(owned[0].get("marketplace_order_id") or owned[0].get("codigo_pedido_externo") or "")
    conversations = (supabase_db.table("mercadolivre_chat_conversations").select("pack_id,context_hash,order_ids")
                     .eq("marketplace_integration_id", int(integration_id)).execute().data or [])
    conversation = next((row for row in conversations if external in [str(value) for value in (_json(row.get("order_ids"), []) or [])]), None)
    pack_id = str((body.get("pack_id") or (conversation or {}).get("pack_id") or external))
    pack_messages = (supabase_db.table("mercadolivre_chat_messages").select("*")
                     .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", pack_id)
                     .order("created_at").execute().data or [])
    context_hash = _context_hash(pack_messages) if pack_messages else hashlib.sha256(
        f"manual:{integration_id}:{pedido_id}:{item_id}:{_now()}".encode()).hexdigest()
    rows = (supabase_db.table("mercadolivre_personalizations").insert({
        "marketplace_integration_id": int(integration_id), "pedido_id": int(pedido_id),
        "item_pedido_id": item_id, "pack_id": pack_id, "provider_order_id": external,
        "provider_item_id": f"manual-item-{item_id}-{int(time.time())}",
        "quantity_to_personalize": quantity, "customization_name": name,
        "customization_initial": initial, "status": "SUCCESS", "reasoning": "Confirmado manualmente.",
        "context_hash": context_hash, "source": "manual", "confirmed": True,
        "confirmed_by": user_id, "confirmed_at": _now(),
    }).execute().data or [])
    supabase_db.table("mercadolivre_chat_conversations").update({
        "context_hash": context_hash, "ai_status": "manual_reviewed", "updated_at": _now(),
    }).eq("marketplace_integration_id", int(integration_id)).eq("pack_id", pack_id).execute()
    supabase_db.table("mercadolivre_personalization_logs").insert({
        "marketplace_integration_id": int(integration_id), "pack_id": pack_id,
        "pedido_id": int(pedido_id), "status": "manual", "model_result": {
            "item_pedido_id": item_id, "customization_name": name,
            "customization_initial": initial, "quantity_to_personalize": quantity,
        }, "metadata": {"confirmed_by": user_id},
    }).execute()
    return rows[0] if rows else {"pedido_id": int(pedido_id), "item_pedido_id": item_id,
                                "confirmed": True, "customization_name": name}


def printable_personalizations(integration_id: int, pedido_id: int) -> dict:
    """Return valid, current-context names keyed by canonical item ID."""
    _integration(integration_id, active=False)
    orders = (supabase_db.table("pedidos").select("id,codigo_pedido_externo,marketplace_order_id")
              .eq("id", int(pedido_id)).eq("marketplace_integration_id", int(integration_id))
              .limit(1).execute().data or [])
    if not orders:
        raise LookupError("Pedido não pertence à conta Mercado Livre informada")
    items = (supabase_db.table("itens_pedido").select("id,quantidade,personalizado,descricao,titulo_anuncio")
             .eq("pedido_id", int(pedido_id)).execute().data or [])
    from nistiprint_shared.services.personalized_classification_service import classify_items
    items = [item for item in items if item.get("personalizado") or classify_items([{
        "descricao": item.get("titulo_anuncio") or item.get("descricao")
    }]).matched_items]
    if not items:
        return {"ready": True, "by_item_id": {}, "message": None}
    all_stored = (supabase_db.table("mercadolivre_personalizations").select("*")
                  .eq("marketplace_integration_id", int(integration_id)).eq("pedido_id", int(pedido_id))
                  .execute().data or [])
    pack_ids = {str(row.get("pack_id")) for row in all_stored}
    conversations = (supabase_db.table("mercadolivre_chat_conversations").select("pack_id,context_hash,last_ai_executed_at,ai_status")
                     .eq("marketplace_integration_id", int(integration_id)).execute().data or [])
    known_conversations = {str(row["pack_id"]): row for row in conversations}
    current_messages = {}
    for pack_id in pack_ids:
        current_messages[pack_id] = (supabase_db.table("mercadolivre_chat_messages").select("provider_message_id,sender_role")
            .eq("marketplace_integration_id", int(integration_id)).eq("pack_id", pack_id).execute().data or [])
    pending_events = (supabase_db.table("mercadolivre_chat_inbox").select("id", count="exact")
                      .eq("marketplace_integration_id", int(integration_id))
                      .in_("status", ["pending", "retry", "processing", "unmatched"]).execute())
    has_pending_events = bool(getattr(pending_events, "count", None) or getattr(pending_events, "data", None))
    return _evaluate_printable_personalizations(
        int(integration_id), items, all_stored, known_conversations,
        current_messages, has_pending_events,
    )


def printable_personalizations_many(orders: list[dict], items_by_order: dict[int, list[dict]]) -> dict[int, dict]:
    """Resolve as personalizações imprimíveis de um lote com leituras agrupadas."""
    from nistiprint_shared.services.personalized_classification_service import classify_items

    pedidos_por_id = {int(order["id"]): order for order in orders if order.get("id") is not None}
    ids_por_integracao: dict[int, list[int]] = {}
    itens_personalizados: dict[int, list[dict]] = {}
    resultados = {}
    for pedido_id, order in pedidos_por_id.items():
        personalized_items = [item for item in items_by_order.get(pedido_id, [])
            if item.get("personalizado") or classify_items([{
                "descricao": item.get("titulo_anuncio") or item.get("descricao")
            }]).matched_items]
        itens_personalizados[pedido_id] = personalized_items
        if not personalized_items:
            resultados[pedido_id] = {"ready": True, "by_item_id": {}, "message": None}
            continue
        integration_id = order.get("marketplace_integration_id")
        if not integration_id:
            resultados[pedido_id] = {"ready": False, "by_item_id": {}, "message": "Conta Mercado Livre não identificada."}
            continue
        try:
            integration_id = int(integration_id)
        except (TypeError, ValueError):
            resultados[pedido_id] = {"ready": False, "by_item_id": {}, "message": "Conta Mercado Livre não identificada."}
            continue
        ids_por_integracao.setdefault(integration_id, []).append(pedido_id)

    if not ids_por_integracao:
        for pedido_id in pedidos_por_id:
            resultados.setdefault(pedido_id, {"ready": True, "by_item_id": {}, "message": None})
        return resultados

    integrations = list(ids_por_integracao)
    for integration_id in integrations:
        try:
            _integration(integration_id, active=False)
        except Exception:
            logger.warning("Falha ao validar conta Mercado Livre para impressão em lote", exc_info=True)
            for pedido_id in ids_por_integracao[integration_id]:
                resultados[pedido_id] = {"ready": False, "by_item_id": {}, "message": "Conta Mercado Livre indisponível."}

    todos_os_ids = [pedido_id for ids in ids_por_integracao.values() for pedido_id in ids]
    stored_rows = (supabase_db.table("mercadolivre_personalizations").select("*")
        .in_("marketplace_integration_id", integrations).in_("pedido_id", todos_os_ids).execute().data or [])
    stored_por_pedido: dict[int, list[dict]] = {}
    pack_ids = set()
    provider_ids = set()
    for row in stored_rows:
        try:
            pedido_id = int(row.get("pedido_id"))
        except (TypeError, ValueError):
            continue
        stored_por_pedido.setdefault(pedido_id, []).append(row)
        if row.get("pack_id"):
            pack_ids.add(str(row["pack_id"]))
        details = _json(row.get("details"), {}) or {}
        for value in (
            details.get("name_source_message_id") or row.get("provider_message_id"),
            details.get("initial_source_message_id"),
        ):
            if value and str(value) != "message_to_seller":
                provider_ids.add(str(value))

    conversations = []
    if pack_ids:
        conversations = (supabase_db.table("mercadolivre_chat_conversations")
            .select("marketplace_integration_id,pack_id,context_hash,last_ai_executed_at,ai_status")
            .in_("marketplace_integration_id", integrations).in_("pack_id", sorted(pack_ids)).execute().data or [])
    conversas_por_integracao_pack = {
        (int(row["marketplace_integration_id"]), str(row["pack_id"])): row
        for row in conversations
    }

    messages = []
    if provider_ids:
        messages = (supabase_db.table("mercadolivre_chat_messages").select("marketplace_integration_id,pack_id,provider_message_id,sender_role")
            .in_("marketplace_integration_id", integrations).in_("provider_message_id", sorted(provider_ids)).execute().data or [])
    mensagens_por_integracao_pack: dict[tuple[int, str], list[dict]] = {}
    for row in messages:
        key = (int(row["marketplace_integration_id"]), str(row["pack_id"]))
        mensagens_por_integracao_pack.setdefault(key, []).append(row)

    integrations_com_fila = set()
    for integration_id in integrations:
        pending = (supabase_db.table("mercadolivre_chat_inbox").select("id")
            .eq("marketplace_integration_id", integration_id)
            .in_("status", ["pending", "retry", "processing", "unmatched"]).limit(1).execute().data or [])
        if pending:
            integrations_com_fila.add(integration_id)

    for integration_id, pedido_ids in ids_por_integracao.items():
        for pedido_id in pedido_ids:
            if pedido_id in resultados:
                continue
            items = itens_personalizados.get(pedido_id, [])
            if not items:
                resultados[pedido_id] = {"ready": True, "by_item_id": {}, "message": None}
                continue
            rows = stored_por_pedido.get(pedido_id, [])
            packs_do_pedido = {str(row.get("pack_id")) for row in rows if row.get("pack_id")}
            conversas = {pack: conversas_por_integracao_pack[(integration_id, pack)]
                for pack in packs_do_pedido if (integration_id, pack) in conversas_por_integracao_pack}
            mensagens = {pack: mensagens_por_integracao_pack.get((integration_id, pack), []) for pack in packs_do_pedido}
            resultados[pedido_id] = _evaluate_printable_personalizations(
                integration_id, items, rows, conversas, mensagens,
                integration_id in integrations_com_fila,
            )

    for pedido_id in pedidos_por_id:
        resultados.setdefault(pedido_id, {"ready": False, "by_item_id": {}, "message": "Conta Mercado Livre não identificada."})
    return resultados


def _evaluate_printable_personalizations(
    integration_id: int,
    items: list[dict],
    all_stored: list[dict],
    conversations: dict[str, dict],
    current_messages: dict[str, list[dict]],
    has_pending_events: bool,
) -> dict:
    """Aplica as regras de validade sem fazer consultas ao banco."""
    known_conversations = conversations
    current_rows = [row for row in all_stored if row.get("source") == "manual" or
                    row.get("marketplace_integration_id") == int(integration_id)]
    item_quantities = {int(item["id"]): max(1, int(item.get("quantidade") or 1)) for item in items}
    latest_success: dict[tuple[str, int], tuple[str, str]] = {}
    for row in current_rows:
        if row.get("status") == "SUCCESS" and row.get("marketplace_integration_id") == int(integration_id):
            key = (str(row.get("pack_id")), int(row.get("item_pedido_id") or 0))
            if (known_conversations.get(key[0]) or {}).get("context_hash") and row.get("context_hash") != (known_conversations.get(key[0]) or {}).get("context_hash"):
                continue
            latest_success[key] = max(latest_success.get(key, ("", "")), (
                str(row.get("updated_at") or row.get("created_at") or ""), str(row.get("id") or "")))
    valid = []
    unresolved_rows = []
    for row in current_rows:
        item_id = int(row.get("item_pedido_id") or 0)
        details = _json(row.get("details"), {}) or {}
        buyer_message_ids = {str(message.get("provider_message_id")) for message in current_messages.get(str(row.get("pack_id")), [])
                             if message.get("sender_role") == "buyer"}
        try:
            quantity = int(row.get("quantity_to_personalize") or 0)
        except (TypeError, ValueError):
            quantity = 0
        source_ok = row.get("source") == "manual" or (
            (not row.get("customization_name") or str(details.get("name_source_message_id")
                or row.get("provider_message_id") or "") in buyer_message_ids | {"message_to_seller"})
            and (not row.get("customization_initial") or str(details.get("initial_source_message_id") or "") in buyer_message_ids | {"message_to_seller"})
        )
        row_key = (str(row.get("pack_id")), item_id)
        row_time = (str(row.get("updated_at") or row.get("created_at") or ""), str(row.get("id") or ""))
        current_success = row.get("status") == "SUCCESS" and row.get("context_hash") == (known_conversations.get(row_key[0]) or {}).get("context_hash")
        if (row.get("status") == "SUCCESS" and row.get("marketplace_integration_id") == int(integration_id)
                and (row_time == latest_success.get(row_key) or not current_success)
                and item_id in item_quantities and 1 <= quantity <= item_quantities[item_id] and source_ok):
            valid.append(row)
        elif (str(row.get("status") or "").upper() != "NO_PERSONALIZATION_FOUND"
              and row.get("marketplace_integration_id") == int(integration_id)):
            unresolved_rows.append(row)
    by_item: dict[int, list[dict]] = {}
    for row in valid:
        by_item.setdefault(int(row["item_pedido_id"]), []).append({
            "customization_name": row.get("customization_name"),
            "customization_initial": row.get("customization_initial"),
            "quantity_to_personalize": row.get("quantity_to_personalize", 1),
            "status": row.get("status"), "confirmed": bool(row.get("confirmed")),
        })
    ready = not unresolved_rows and not has_pending_events
    for item in items:
        rows = by_item.get(int(item["id"]), [])
        names = sum(int(row.get("quantity_to_personalize") or 0) for row in rows)
        if not rows or names != max(1, int(item.get("quantidade") or 1)):
            ready = False
    return {"ready": ready, "by_item_id": by_item,
            "message": None if ready else "Personalização pendente, desatualizada ou aguardando sincronização de mensagens."}
