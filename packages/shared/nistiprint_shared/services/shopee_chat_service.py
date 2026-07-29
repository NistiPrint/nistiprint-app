"""Shopee SellerChat push classification and idempotent persistence."""

from datetime import datetime, timezone
from typing import Any
import logging

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.integration_resolution_service import integration_resolution_service
from nistiprint_shared.services.shopee_chat_api import get_all_chat_messages

logger = logging.getLogger(__name__)

SHOPEE_CHAT_CODE = 10
SHOPEE_ORDER_CODE = 3


def _body(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def classify_shopee_webhook(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    body = _body(payload)
    code = body.get("code", payload.get("code"))
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    if code == SHOPEE_CHAT_CODE:
        return "chat"
    if code == SHOPEE_ORDER_CODE:
        return "order"
    if {"conversation_id", "message_id", "messages", "message", "msg_id"}.intersection(body):
        return "chat"
    return "unknown"


def extract_chat_push(payload: dict) -> tuple[str, dict]:
    body = _body(payload)
    push_type = str(body.get("type") or "").strip().lower()
    content = body.get("content")
    return push_type, content if isinstance(content, dict) else {}


def extract_chat_provider_event_id(payload: dict) -> str | None:
    push_type, content = extract_chat_push(payload)
    value = content.get("message_id") if push_type == "message" else None
    return str(value) if value not in (None, "") else None


def _iso_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_chat_message(raw: dict, *, integration_id: int, shop_id: Any = None,
                           webhook_event_id: int | None = None,
                           ingestion_source: str = "webhook") -> dict:
    provider_id = raw.get("id") or raw.get("message_id") or raw.get("msg_id")
    if provider_id in (None, ""):
        raise ValueError("mensagem Shopee sem id")
    created = _iso_timestamp(raw.get("created_timestamp") or raw.get("created_at") or raw.get("timestamp"))
    return {
        "id": str(provider_id), "installed_integration_id": integration_id,
        "provider_message_id": str(provider_id), "webhook_event_id": webhook_event_id,
        "shop_id": raw.get("shop_id", shop_id), "request_id": raw.get("request_id"),
        "from_id": raw.get("from_id"), "to_id": raw.get("to_id"),
        "from_shop_id": raw.get("from_shop_id"), "to_shop_id": raw.get("to_shop_id"),
        "from_user_name": raw.get("from_user_name"), "to_user_name": raw.get("to_user_name"),
        "type": raw.get("message_type") or raw.get("type") or "text",
        "conversation_id": str(raw.get("conversation_id")) if raw.get("conversation_id") is not None else None,
        "created_timestamp": created, "created_at": created, "status": raw.get("status"),
        "message_option": raw.get("message_option"), "source": raw.get("source") or "webhook",
        "content": raw.get("content"), "faq_info": raw.get("faq_info"),
        "source_content": raw.get("source_content"), "raw_json": raw, "raw_payload": raw,
        "business_type": int(raw.get("business_type") or 0), "region": raw.get("region"),
        "is_in_chatbot_session": raw.get("is_in_chatbot_session"),
        "quoted_msg": raw.get("quoted_msg"), "sub_account_id": raw.get("sub_account_id"),
        "sub_account_name": raw.get("sub_account_name"),
        "shopee_chatbot_replied": raw.get("shopee_chatbot_replied"),
        "received_at": datetime.now(timezone.utc).isoformat(), "ingestion_source": ingestion_source,
    }


class ShopeeChatIngestService:
    def reconcile_conversation(self, integration: dict, conversation_id: str, *, max_pages: int = 100) -> dict:
        integration_id = integration.get("id")
        if not integration_id:
            return {"status": "error", "error_type": "integration_not_found",
                    "message": "Integracao Shopee sem id"}
        fetched = get_all_chat_messages(
            integration, str(conversation_id), business_type=0, max_pages=max_pages
        )
        if fetched.get("error"):
            return {"status": "error", "error_type": fetched.get("error_type") or "chat_fetch_failed",
                    "message": fetched.get("error"), "retryable": bool(fetched.get("retryable")),
                    "messages_fetched": len(fetched.get("messages") or [])}
        messages = [row for row in (fetched.get("messages") or [])
                    if int(row.get("business_type") or 0) == 0]
        rows = [normalize_chat_message(row, integration_id=int(integration_id),
                                       shop_id=(integration.get("config") or {}).get("shop_id"),
                                       ingestion_source="sellerchat_api") for row in messages]
        if rows:
            supabase_db.table("mensagem_chat_shopee").upsert(
                rows, on_conflict="installed_integration_id,provider_message_id"
            ).execute()
        return {"status": "success", "event_status": "chat_reconciled",
                "messages_fetched": len(messages), "messages_upserted": len(rows),
                "conversation_id": str(conversation_id)}

    def process(self, payload: dict, *, integration_id: int | None = None,
                webhook_event_id: int | None = None) -> dict:
        if classify_shopee_webhook(payload) != "chat":
            return {"status": "skipped", "event_status": "not_chat"}
        body = _body(payload)
        push_type, content = extract_chat_push(payload)
        if push_type == "notification":
            return {"status": "skipped", "event_status": "skipped_chat_notification",
                    "provider_topic": content.get("type"), "conversation_id": content.get("conversation_id")}
        if push_type != "message":
            return {"status": "error", "error_type": "invalid_chat_push_type",
                    "message": "Push SellerChat sem data.type=message"}
        business_type = int(content.get("business_type") or 0)
        if business_type == 11:
            return {"status": "skipped", "event_status": "skipped_affiliate_chat",
                    "conversation_id": content.get("conversation_id")}
        if business_type != 0:
            return {"status": "error", "error_type": "unsupported_business_type",
                    "message": f"business_type SellerChat nao suportado: {business_type}"}
        shop_id = content.get("shop_id") or payload.get("shop_id")
        integration = ({"id": integration_id, "plataforma_slug": "shopee"}
                       if integration_id is not None else
                       (integration_resolution_service.resolve_marketplace_by_shop_id(str(shop_id)) if shop_id else None))
        if not integration or str(integration.get("plataforma_slug") or "").lower() != "shopee":
            return {"status": "error", "error_type": "integration_not_found", "message": "Shop Shopee sem integracao ativa"}
        if not content.get("message_id") or not content.get("conversation_id"):
            return {"status": "error", "error_type": "invalid_chat_message",
                    "message": "Push SellerChat sem message_id ou conversation_id",
                    "marketplace_integration_id": integration.get("id")}
        rows = [normalize_chat_message(content, integration_id=int(integration["id"]), shop_id=shop_id,
                                       webhook_event_id=webhook_event_id)]
        supabase_db.table("mensagem_chat_shopee").upsert(rows, on_conflict="installed_integration_id,provider_message_id").execute()
        return {"status": "success", "event_status": "chat_persisted", "messages": len(rows),
                "marketplace_integration_id": integration.get("id"), "conversation_id": rows[0].get("conversation_id"),
                "provider_topic": content.get("message_type"), "provider_resource": "chat_message"}


shopee_chat_ingest_service = ShopeeChatIngestService()
