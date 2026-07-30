"""Post-ACK acceptance, signature verification and event audit helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.shopee_chat_service import extract_chat_provider_event_id


@dataclass(frozen=True)
class SignatureResult:
    status: str
    valid: bool
    enforce: bool
    reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.enforce and not self.valid


def _payload(envelope: dict[str, Any]) -> dict[str, Any]:
    value = envelope.get("parsed_payload", envelope.get("payload"))
    return value if isinstance(value, dict) else {}


def _body(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _secrets(source: str) -> list[str]:
    raw = os.getenv(f"INGEST_WEBHOOK_SECRETS_{source.upper()}", "")
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, list):
            return [str(value) for value in decoded if str(value)]
    except (TypeError, ValueError):
        pass
    return [value.strip() for value in raw.split(",") if value.strip()]


def _policy(source: str) -> str:
    return os.getenv(f"INGEST_SIGNATURE_POLICY_{source.upper()}", "optional").strip().lower()


def _compare_hmac(raw: str, signature: str, secrets: list[str]) -> bool:
    provided = re.sub(r"^(sha256=|v1=)", "", signature.strip(), flags=re.I)
    return any(hmac.compare_digest(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest(), provided)
               for secret in secrets)


def _validate_meli(envelope: dict[str, Any], secrets: list[str]) -> tuple[bool | None, str]:
    headers, payload = envelope.get("headers") or {}, _payload(envelope)
    signature, request_id = headers.get("x-signature", ""), headers.get("x-request-id", "")
    parts = dict(re.findall(r"([a-z0-9]+)=([^,]+)", signature.lower()))
    ts, provided = parts.get("ts"), parts.get("v1")
    data_id = (_body(payload).get("id") or payload.get("id"))
    if not (ts and provided and request_id and data_id is not None and secrets):
        return None, "missing_signature_material"
    manifest = f"id:{str(data_id).lower()};request-id:{request_id};ts:{ts};"
    valid = any(hmac.compare_digest(hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest(), provided)
                for secret in secrets)
    return valid, "mercadolivre_manifest_hmac_sha256"


def validate_signature(envelope: dict[str, Any]) -> SignatureResult:
    source = str(envelope.get("source") or "").lower()
    policy, secrets = _policy(source), _secrets(source)
    enforce = policy == "required"
    if policy == "disabled":
        return SignatureResult("signature_disabled", True, False)
    headers, raw = envelope.get("headers") or {}, str(envelope.get("raw_body") or "")
    if source == "bling":
        signature = headers.get("x-bling-signature-256") or headers.get("x-hub-signature-256")
        result = _compare_hmac(raw, signature, secrets) if signature and secrets else None
        strategy = "raw_body_hmac_sha256"
    elif source == "mercadolivre":
        result, strategy = _validate_meli(envelope, secrets)
    elif source == "shopee":
        signature = headers.get("x-shopee-signature") or headers.get("x-hub-signature-256")
        result = _compare_hmac(raw, signature, secrets) if signature and secrets else None
        strategy = "raw_body_hmac_sha256"
    else:
        result, strategy = None, "unsupported_source"
    if result is True:
        return SignatureResult("signature_valid", True, enforce, strategy)
    if result is False:
        return SignatureResult("discarded_invalid_signature", False, True, strategy)
    return SignatureResult("discarded_signature_unverifiable" if enforce else "signature_unverified",
                           not enforce, enforce, strategy)


def extract_identity(envelope: dict[str, Any]) -> dict[str, str | None]:
    source, payload = str(envelope.get("source") or "").lower(), _payload(envelope)
    body = _body(payload)
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    provider_id = envelope.get("provider_delivery_id")
    if source == "shopee":
        provider_id = provider_id or extract_chat_provider_event_id(payload) or payload.get("msg_id") or body.get("event_id")
        scope = content.get("shop_id") or payload.get("shop_id") or body.get("shop_id")
        order_id = content.get("order_sn") or body.get("order_sn")
    elif source == "mercadolivre":
        provider_id = provider_id or body.get("_id") or body.get("id")
        scope = body.get("user_id") or payload.get("user_id")
        resource = str(body.get("resource") or "")
        order_id = body.get("order_id") or (resource.split("/orders/")[1].split("/")[0] if "/orders/" in resource else None)
    else:
        provider_id = provider_id or body.get("eventId") or body.get("event_id") or body.get("id")
        scope = body.get("companyId") or body.get("company_id") or payload.get("companyId")
        order_id = body.get("numeroLoja") or body.get("numero_loja")
    payload_hash = str(envelope.get("body_sha256") or hashlib.sha256(str(envelope.get("raw_body") or "").encode()).hexdigest())
    return {"provider_event_id": str(provider_id) if provider_id not in (None, "") else None,
            "dedupe_scope": str(scope) if scope not in (None, "") else "source",
            "dedupe_key": f"provider:{provider_id}" if provider_id not in (None, "") else f"sha256:{payload_hash}",
            "payload_hash": payload_hash,
            "resolved_order_id": str(order_id) if order_id not in (None, "") else None}


def accept_event(envelope: dict[str, Any]) -> dict[str, Any]:
    identity = extract_identity(envelope)
    correlation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nistiprint:webhook:{envelope['event_id']}"))
    response = supabase_db.rpc("accept_reliable_webhook_event", {
        "p_source": envelope["source"], "p_dedupe_scope": identity["dedupe_scope"],
        "p_dedupe_key": identity["dedupe_key"], "p_provider_event_id": identity["provider_event_id"],
        "p_payload_hash": identity["payload_hash"], "p_raw_payload": _payload(envelope),
        "p_raw_body": envelope.get("raw_body"),
        "p_received_at": envelope.get("received_at"), "p_correlation_id": correlation_id,
        "p_resolved_order_id": identity["resolved_order_id"],
    }).execute()
    data = response.data or []
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict) or not row.get("webhook_event_id"):
        raise RuntimeError("accept_reliable_webhook_event returned no event")
    return row


def record_signature_result(event_id: int, signature: SignatureResult) -> None:
    supabase_db.table("webhook_events").update({
        "signature_status": signature.status,
        "signature_checked_at": datetime.now(timezone.utc).isoformat(),
        "signature_error": signature.reason if not signature.valid else None,
    }).eq("id", event_id).execute()


def finalize_event(event_id: int, status: str, *, result: dict[str, Any] | None = None,
                   error_type: str | None = None, error_message: str | None = None) -> None:
    result = result or {}
    fields = {"last_status": status, "last_attempt_at": datetime.now(timezone.utc).isoformat(),
              "next_attempt_after": None, "processing_started_at": None,
              "processing_correlation_id": None, "last_error_type": error_type,
              "last_error_message": str(error_message)[:4000] if error_message else None}
    for key in (
        "pedido_id", "provider_topic", "provider_resource",
        "provider_resource_type", "provider_resource_id", "resolution_status",
        "resolved_order_ids", "provider_updated_at", "lifecycle_stage",
    ):
        if result.get(key) is not None:
            fields[key] = result[key]
    resolved_ids = result.get("resolved_order_ids") or []
    resolved_order_id = result.get("external_order_id") or (
        resolved_ids[0] if isinstance(resolved_ids, list) and resolved_ids else None
    )
    if resolved_order_id is not None:
        fields["resolved_order_id"] = str(resolved_order_id)
    supabase_db.table("webhook_events").update(fields).eq("id", event_id).execute()


def mark_retry_event(event_id: int, attempt: int, error_type: str, message: str,
                     next_attempt_at: str) -> None:
    supabase_db.table("webhook_events").update({
        "last_status": "pending_retry", "attempt_count": max(1, int(attempt)),
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "next_attempt_after": next_attempt_at, "processing_started_at": None,
        "processing_correlation_id": None, "last_error_type": error_type,
        "last_error_message": str(message)[:4000],
    }).eq("id", event_id).execute()


def record_failed_attempt(event_id: int, attempt: int, queue: str, error_type: str,
                          message: str, result: dict[str, Any] | None = None) -> None:
    supabase_db.table("webhook_event_attempts").insert({
        "webhook_event_id": event_id, "correlation_id": str(uuid.uuid4()),
        "attempt_number": max(1, int(attempt)), "status": "failed", "queue_name": queue,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(), "error_type": error_type,
        "error_message": str(message)[:4000], "result_summary": result or {},
    }).execute()
