"""Continuous reliable-ingest services (one role per process)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import socket
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from nistiprint_shared.services.reliable_ingest_queue import (
    CHAT_PROCESSING, CHAT_READY, DLQ, INBOX_PROCESSING, INBOX_READY,
    ORDERS_PROCESSING, ORDERS_READY, RETRY_DELAYS, claim, complete, forward,
    move_to_dlq, queue_lengths, reap_expired_leases, reap_orphaned_processing,
    redis_client, replay_spool_once, requeue_due_retries, schedule_retry,
)
from nistiprint_shared.services.reliable_ingest_service import (
    SignatureResult, accept_event, finalize_event, mark_retry_event, record_failed_attempt,
    record_signature_result, validate_signature,
)

logger = logging.getLogger(__name__)
WORKER = f"{socket.gethostname()}:{os.getpid()}"
MAX_ATTEMPTS = int(os.getenv("INGEST_MAX_ATTEMPTS", "7"))
SIGNATURE_VERDICT_GRACE_SECONDS = max(
    1.0, float(os.getenv("INGEST_SIGNATURE_VERDICT_GRACE_SECONDS", "30"))
)
TERMINAL_ERRORS = {
    "unsupported_source", "unsupported_business_type", "not_chat",
    "invalid_provider_resource", "invalid_provider_resource_id",
    "provider_topic_resource_mismatch", "provider_parameter_error",
    "provider_access_forbidden", "provider_identity_mismatch",
    "marketplace_integration_ambiguous",
}


class SignatureVerdictPending(RuntimeError):
    error_type = "signature_verdict_pending"
    retry_after = 1
    retryable = True


def _payload(item):
    value = item.get("parsed_payload", item.get("payload"))
    return value if isinstance(value, dict) else {}


def _is_chat(item):
    if item.get("source") != "shopee":
        return False
    from nistiprint_shared.services.marketplace_adapters import shopee_adapter
    return shopee_adapter.parse_webhook(_payload(item)).classification == "chat"


def _heartbeat(role, client):
    client.set(f"np:ingest:heartbeat:{role}", datetime.now(timezone.utc).isoformat(), ex=120)


def _is_within_signature_grace(item):
    try:
        received_at = datetime.fromisoformat(
            str(item["received_at"]).replace("Z", "+00:00")
        )
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - received_at.astimezone(timezone.utc)).total_seconds()
        return age <= SIGNATURE_VERDICT_GRACE_SECONDS
    except (KeyError, TypeError, ValueError):
        return True


def _signature_result(item, client):
    if item.get("source") != "shopee":
        return validate_signature(item), None
    verdict_key = f"np:ingest:signature:{item['event_id']}"
    raw = client.get(verdict_key)
    if raw:
        verdict = json.loads(raw)
        status = verdict.get("signature_status")
        if status == "signature_valid":
            return SignatureResult(status, True, True, "n8n_post_ack_hmac_sha256"), verdict_key
        if status == "discarded_invalid_signature":
            enforce = os.getenv("INGEST_SIGNATURE_POLICY_SHOPEE", "optional").strip().lower() == "required"
            effective_status = status if enforce else "signature_unverified"
            return SignatureResult(
                effective_status,
                not enforce,
                enforce,
                "n8n_post_ack_hmac_sha256_mismatch",
            ), verdict_key
        return validate_signature(item), verdict_key
    if int(item.get("attempt") or 0) < 3 and _is_within_signature_grace(item):
        raise SignatureVerdictPending("Shopee signature verdict is not available yet")
    return validate_signature(item), None


def route_once(client=None):
    r = client or redis_client()
    item = claim(INBOX_READY, INBOX_PROCESSING, WORKER, client=r)
    if not item:
        return False
    try:
        signature, verdict_key = _signature_result(item, r)
        accepted = ({"webhook_event_id": int(item["webhook_event_id"]), "should_process": True}
                    if item.get("webhook_event_id") else accept_event(item))
        event_id = int(accepted["webhook_event_id"])
        item["webhook_event_id"] = event_id
        record_signature_result(event_id, signature)
        if verdict_key:
            r.delete(verdict_key)
        if signature.terminal:
            finalize_event(event_id, signature.status, error_type=signature.status,
                           error_message=signature.reason)
            if not complete(item, INBOX_PROCESSING, r):
                raise RuntimeError("claim lost while discarding signature")
            return True
        item["signature_status"] = signature.status
        if not bool(accepted.get("should_process", True)):
            complete(item, INBOX_PROCESSING, r)
            return True
        destination = CHAT_READY if _is_chat(item) else ORDERS_READY
        if not forward(item, INBOX_PROCESSING, destination, r):
            raise RuntimeError("claim lost while routing")
        return True
    except SignatureVerdictPending as exc:
        logger.info("Shopee signature verdict pending event=%s attempt=%s",
                    item.get("event_id"), item.get("attempt", 0))
        _retry(item, INBOX_PROCESSING, r, exc)
        return True
    except Exception as exc:
        logger.exception("router failed")
        _retry(item, INBOX_PROCESSING, r, exc)
        return True


def _process_order(item):
    source, payload = str(item.get("source") or "").lower(), _payload(item)
    event_id = int(item["webhook_event_id"])
    if source == "bling":
        from nistiprint_shared.services.bling_order_processing_service import process_webhook
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        result = process_webhook(body,
            bling_integration_hint=payload.get("bling_integration_id") or payload.get("blingIntegrationId"),
            company_id=payload.get("companyId") or payload.get("company_id"),
            webhook_event_id=event_id)
    elif source in ("shopee", "mercadolivre"):
        from nistiprint_shared.services.marketplace_webhook_ingest_service import marketplace_webhook_ingest_service
        result = marketplace_webhook_ingest_service.process(source, payload, webhook_event_id=event_id)
    else:
        result = {"status": "error", "error_type": "unsupported_source",
                  "message": f"source nao suportado: {source}"}
    return result


def _process_chat(item):
    if item.get("source") != "shopee":
        return {"status": "error", "error_type": "unsupported_source",
                "message": "somente chat Shopee entra nesta fila"}
    from nistiprint_shared.services.shopee_chat_service import shopee_chat_ingest_service
    return shopee_chat_ingest_service.process(_payload(item),
        webhook_event_id=int(item["webhook_event_id"]))


def _consume_once(ready, processing, processor, client=None):
    r = client or redis_client()
    item = claim(ready, processing, WORKER, client=r)
    if not item:
        return False
    event_id = item.get("webhook_event_id")
    try:
        result = processor(item)
        status = result.get("status")
        if status in ("success", "skipped"):
            final_status = result.get("event_status") or status
            finalize_event(int(event_id), final_status, result=result)
            if not complete(item, processing, r):
                raise RuntimeError("claim lost after idempotent domain success")
        else:
            error = RuntimeError(result.get("message") or "processing_error")
            error.error_type = result.get("error_type") or "processing_error"
            error.retry_after = result.get("retry_after")
            if "retryable" in result:
                error.retryable = bool(result["retryable"])
            else:
                error.retryable = (
                    error.error_type == "processing_error"
                    or error.error_type not in TERMINAL_ERRORS
                )
            _retry(item, processing, r, error, result=result)
        return True
    except Exception as exc:
        logger.exception("consumer failed queue=%s", ready)
        _retry(item, processing, r, exc)
        return True


def _retry(item, processing, client, exc, result=None):
    attempt = int(item.get("attempt") or 0) + 1
    event_id = item.get("webhook_event_id")
    error_type = str(getattr(exc, "error_type", type(exc).__name__))
    retryable = bool(getattr(exc, "retryable", True))
    if error_type == "provider_resource_not_found":
        try:
            received_at = datetime.fromisoformat(
                str(item.get("received_at")).replace("Z", "+00:00")
            )
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            age_seconds = (
                datetime.now(timezone.utc) - received_at.astimezone(timezone.utc)
            ).total_seconds()
        except (TypeError, ValueError):
            age_seconds = 301
        retryable = attempt <= 2 and age_seconds <= 300
    if not retryable or attempt >= MAX_ATTEMPTS:
        if event_id:
            finalize_event(int(event_id), "manual_intervention" if retryable else "failed_terminal",
                           result=result, error_type=error_type, error_message=str(exc))
            record_failed_attempt(int(event_id), attempt, processing, error_type, str(exc), result)
        if not move_to_dlq(item, processing, client, reason=error_type):
            logger.error("claim lost while moving event=%s to DLQ", item.get("event_id"))
        return
    retry_after = getattr(exc, "retry_after", None)
    default_delay = RETRY_DELAYS[min(max(attempt - 1, 0), len(RETRY_DELAYS) - 1)]
    delay = max(1.0, float(retry_after if retry_after is not None else default_delay))
    next_at = datetime.fromtimestamp(time.time() + delay, tz=timezone.utc).isoformat()
    if not schedule_retry(item, processing, attempt, client, retry_after=delay):
        logger.error("claim lost while scheduling retry event=%s", item.get("event_id"))
        return
    if event_id:
        mark_retry_event(int(event_id), attempt, error_type, str(exc), next_at)
        record_failed_attempt(int(event_id), attempt, processing, error_type, str(exc), result)


def _send_alert(subject, body):
    host, recipient = os.getenv("SMTP_HOST"), os.getenv("INGEST_ALERT_TO")
    if not host or not recipient:
        logger.warning("alert not sent (SMTP_HOST/INGEST_ALERT_TO missing): %s", subject)
        return
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, os.getenv("SMTP_FROM", recipient), recipient
    message.set_content(body)
    port, timeout = int(os.getenv("SMTP_PORT", "587")), 10
    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if os.getenv("SMTP_STARTTLS", "1") == "1": smtp.starttls()
        if os.getenv("SMTP_USERNAME"): smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)


def monitor_once(client=None):
    r, problems = client or redis_client(), []
    lengths = queue_lengths(r)
    if lengths.get(DLQ, 0): problems.append(f"DLQ={lengths[DLQ]}")
    for queue_name in (INBOX_READY, ORDERS_READY, CHAT_READY):
        raw = r.lindex(queue_name, 0)
        if not raw:
            continue
        try:
            queued_at = datetime.fromisoformat(
                str(json.loads(raw).get("received_at")).replace("Z", "+00:00")
            )
            age = (datetime.now(timezone.utc) - queued_at.astimezone(timezone.utc)).total_seconds()
            if age > 120:
                problems.append(f"backlog_old={queue_name}:{int(age)}s")
        except (TypeError, ValueError, json.JSONDecodeError):
            problems.append(f"backlog_timestamp_invalid={queue_name}")
    try:
        memory = r.info("memory")
        maximum = int(memory.get("maxmemory") or 0)
        used = int(memory.get("used_memory") or 0)
        if maximum and used / maximum >= 0.70:
            problems.append(f"redis_memory={used / maximum:.0%}")
    except Exception:
        logger.exception("could not inspect Redis memory")
    spool = Path(os.getenv("WEBHOOK_SPOOL_DIR", "/data/webhook-spool")) / "ready"
    spool_count = len(list(spool.glob("*.json"))) if spool.exists() else 0
    if spool_count: problems.append(f"spool={spool_count}")
    for role in ("router", "orders", "chat", "retry", "lease", "spool", "archive"):
        if not r.exists(f"np:ingest:heartbeat:{role}"): problems.append(f"worker_down={role}")
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db
        since = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        invalid = (supabase_db.table("webhook_events").select("id", count="exact")
                   .eq("signature_status", "discarded_invalid_signature")
                   .gte("signature_checked_at", since).limit(1).execute())
        if int(invalid.count or 0) >= int(os.getenv("INGEST_INVALID_SIGNATURE_ALERT_THRESHOLD", "10")):
            problems.append(f"invalid_signatures_15m={invalid.count}")
    except Exception:
        logger.exception("could not inspect signature rate")
    if problems and r.set("np:ingest:alert:cooldown", "1", ex=900, nx=True):
        _send_alert("[Nistiprint] Alerta no ingest", "\n".join(problems) + "\n" + json.dumps(lengths, indent=2))
    return problems


def run(role):
    r = redis_client()
    while True:
        try:
            _heartbeat(role, r)
            if role == "router": route_once(r)
            elif role == "orders": _consume_once(ORDERS_READY, ORDERS_PROCESSING, _process_order, r)
            elif role == "chat": _consume_once(CHAT_READY, CHAT_PROCESSING, _process_chat, r)
            elif role == "retry": requeue_due_retries(r); time.sleep(1)
            elif role == "lease": reap_expired_leases(r); reap_orphaned_processing(r); time.sleep(5)
            elif role == "spool": replay_spool_once(r); time.sleep(2)
            elif role == "archive":
                if os.getenv("INGEST_ARCHIVE_ENABLED", "0") == "1":
                    from nistiprint_shared.services.ingest_archive_service import archive_all_once
                    archive_all_once()
                time.sleep(int(os.getenv("INGEST_ARCHIVE_INTERVAL_SECONDS", "300")))
            elif role == "monitor": monitor_once(r); time.sleep(60)
        except Exception:
            logger.exception("service role=%s failed", role)
            time.sleep(2)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("router", "orders", "chat", "retry", "lease", "spool", "archive", "monitor"))
    run(parser.parse_args().role)
