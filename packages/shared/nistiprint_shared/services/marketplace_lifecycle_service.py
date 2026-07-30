"""Provider-aware marketplace lifecycle normalization."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

STATUS_PENDING, STATUS_PAID, STATUS_IN_PRODUCTION, STATUS_READY = 1, 2, 3, 4
STATUS_SHIPPED, STATUS_DELIVERED, STATUS_CANCELLED, STATUS_RETURNED = 5, 6, 7, 8
RETURN_STATES = {
    "return", "returned", "returning", "returning_to_sender",
    "returned_to_sender", "return_to_sender", "return_completed",
    "refund", "refunded", "partial_refund", "partially_refunded",
    "refund_update", "return_update",
    "to_return", "requested", "accepted", "processing",
}

def _value(value: Any) -> str | None:
    return None if value in (None, "") else str(value).strip()

def _lower(value: Any) -> str | None:
    value = _value(value)
    return value.lower() if value else None

def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    return str(value).strip()

def _latest_timestamp(*values: Any) -> str | None:
    parsed = []
    for value in values:
        normalized = _timestamp(value)
        if not normalized:
            continue
        try:
            dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            parsed.append((dt.replace(tzinfo=dt.tzinfo or timezone.utc), normalized))
        except ValueError:
            pass
    return max(parsed, key=lambda item: item[0])[1] if parsed else None

def _state_tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        tokens = set()
        for key, nested in value.items():
            if str(key).lower() in {"status", "substatus", "tag", "tags", "type"}:
                tokens.update(_state_tokens(nested))
        return tokens
    if isinstance(value, (list, tuple, set)):
        tokens = set()
        for nested in value:
            tokens.update(_state_tokens(nested))
        return tokens
    normalized = _lower(value)
    return {normalized.replace("-", "_").replace(" ", "_")} if normalized else set()

def _has_explicit_return_state(*values: Any) -> bool:
    tokens = set()
    for value in values:
        tokens.update(_state_tokens(value))
    return bool(tokens & RETURN_STATES)

@dataclass(frozen=True)
class MarketplaceLifecycle:
    order_status: str | None
    payment_status: str | None
    shipping_status: str | None
    shipping_substatus: str | None
    lifecycle_stage: str
    target_situacao_pedido_id: int | None
    observed_at: str | None
    reason: str

    def to_event(self) -> dict[str, Any]:
        return asdict(self)

def project_operational_status(previous: int | None, target: int | None) -> int | None:
    """Mirror the guarded projection implemented by the database RPC."""
    if target is None:
        return previous
    if target == STATUS_RETURNED or previous == STATUS_RETURNED:
        return STATUS_RETURNED
    if target == STATUS_CANCELLED and previous in (STATUS_SHIPPED, STATUS_DELIVERED):
        return STATUS_RETURNED
    if target == STATUS_CANCELLED:
        return STATUS_CANCELLED
    if previous in (STATUS_DELIVERED, STATUS_CANCELLED):
        return previous
    if target == STATUS_DELIVERED:
        return STATUS_DELIVERED
    if target == STATUS_SHIPPED:
        return STATUS_SHIPPED
    if target == STATUS_READY:
        return STATUS_IN_PRODUCTION if previous == STATUS_IN_PRODUCTION else (
            STATUS_READY if previous in (None, STATUS_PENDING, STATUS_PAID, STATUS_READY) else previous
        )
    if target == STATUS_PAID:
        return STATUS_PAID if previous in (None, STATUS_PENDING, STATUS_PAID) else previous
    if target == STATUS_PENDING:
        return STATUS_PENDING if previous in (None, STATUS_PENDING) else previous
    return previous


def _effective_payment_status(payments: Iterable[dict]) -> str | None:
    statuses = [_lower(p.get("status")) for p in payments if isinstance(p, dict)]
    statuses = [status for status in statuses if status]
    # A failed attempt must not cancel a sale with another valid payment.
    for candidate in ("approved", "authorized", "in_process", "pending", "refunded", "charged_back", "cancelled", "canceled", "rejected"):
        if candidate in statuses:
            return candidate
    return statuses[0] if statuses else None

def resolve_mercadolivre(detail: dict, webhook: dict | None = None) -> MarketplaceLifecycle:
    webhook = webhook or {}
    order, shipment = detail.get("order") or {}, detail.get("shipment") or {}
    payments = order.get("payments") if isinstance(order.get("payments"), list) else []
    order_status = _lower(order.get("status"))
    payment_status = _effective_payment_status(payments)
    shipping_status = _lower(shipment.get("status"))
    shipping_substatus = _lower(shipment.get("substatus"))
    shipped_before = shipping_status in {"shipped", "delivered", "not_delivered"} or bool(
        shipment.get("date_first_printed") or shipment.get("date_shipped")
    )

    if _has_explicit_return_state(
        shipping_substatus, shipment.get("status_history"), order.get("tags")
    ):
        stage, target, reason = "returned", STATUS_RETURNED, "shipment_return"
    elif order_status in {"cancelled", "canceled"}:
        stage, target = ("returned", STATUS_RETURNED) if shipped_before else ("cancelled", STATUS_CANCELLED)
        reason = "order_cancelled_after_shipping" if shipped_before else "order_cancelled"
    elif payment_status in {"refunded", "partially_refunded", "charged_back"}:
        stage, target = ("returned", STATUS_RETURNED) if shipped_before else ("cancelled", STATUS_CANCELLED)
        reason = "payment_reversed_after_shipping" if shipped_before else "payment_reversed"
    elif shipping_status in {"cancelled", "canceled"}:
        stage, target, reason = "cancelled", STATUS_CANCELLED, "shipment_cancelled"
    elif shipping_status == "delivered":
        stage, target, reason = "delivered", STATUS_DELIVERED, "shipment_delivered"
    elif shipping_status == "shipped":
        stage, target, reason = "shipped", STATUS_SHIPPED, "shipment_shipped"
    elif shipping_status == "not_delivered":
        stage, target, reason = "shipping_exception", STATUS_SHIPPED, "shipment_not_delivered"
    elif shipping_status == "ready_to_ship":
        stage, target, reason = "documentation_ready", STATUS_READY, "shipment_ready_to_ship"
    elif (
        payment_status in {"approved", "authorized"}
        or order_status in {"confirmed", "paid"}
        or shipping_status == "handling"
    ):
        stage, target, reason = "paid_preparation", STATUS_PAID, "payment_approved"
    elif payment_status in {"pending", "in_process"} or order_status in {
        "opened", "payment_required", "payment_in_process", "partially_paid",
    }:
        stage, target, reason = "awaiting_payment", STATUS_PENDING, "payment_pending"
    elif payment_status == "rejected":
        stage, target, reason = "cancelled", STATUS_CANCELLED, "only_payment_rejected"
    else:
        stage, target, reason = "unknown", None, "unmapped_provider_state"

    observed_at = _latest_timestamp(shipment.get("last_updated"), order.get("last_updated"), webhook.get("sent"), webhook.get("received"))
    return MarketplaceLifecycle(order_status, payment_status, shipping_status, shipping_substatus, stage, target, observed_at, reason)

def resolve_shopee(detail: dict, webhook: dict | None = None) -> MarketplaceLifecycle:
    webhook = webhook or {}
    raw = detail.get("raw") if isinstance(detail.get("raw"), dict) else {}
    order_status = (_value(detail.get("order_status") or raw.get("order_status")) or "").upper() or None
    return_status = _value(detail.get("return_status") or detail.get("refund_status") or raw.get("return_status") or raw.get("refund_status") or webhook.get("return_status") or webhook.get("refund_status"))
    event_type = _value(webhook.get("event") or webhook.get("event_type") or webhook.get("code") or webhook.get("type"))
    if order_status == "TO_RETURN" or _has_explicit_return_state(return_status, event_type):
        stage, target, reason = "returned", STATUS_RETURNED, "shopee_return_or_refund"
    else:
        mapping = {
            "UNPAID": ("awaiting_payment", STATUS_PENDING),
            "INVOICE_PENDING": ("paid_preparation", STATUS_PAID),
            "READY_TO_SHIP": ("paid_preparation", STATUS_PAID),
            "RETRY_SHIP": ("paid_preparation", STATUS_PAID),
            "PROCESSED": ("documentation_ready", STATUS_READY),
            "SHIPPED": ("shipped", STATUS_SHIPPED),
            "TO_CONFIRM_RECEIVE": ("shipped", STATUS_SHIPPED),
            "COMPLETED": ("delivered", STATUS_DELIVERED),
            "IN_CANCEL": ("cancelled", STATUS_CANCELLED),
            "CANCELLED": ("cancelled", STATUS_CANCELLED),
            "TO_RETURN": ("returned", STATUS_RETURNED),
        }
        stage, target = mapping.get(order_status, ("unknown", None))
        reason = f"shopee_order_status:{order_status or 'missing'}"
    observed_at = _latest_timestamp(detail.get("update_time"), raw.get("update_time"), webhook.get("timestamp"), webhook.get("update_time"))
    return MarketplaceLifecycle(order_status, None, None, return_status, stage, target, observed_at, reason)
