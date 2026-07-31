"""Provider-aware marketplace lifecycle normalization."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

STATUS_PENDING, STATUS_PAID, STATUS_IN_PRODUCTION, STATUS_READY = 1, 2, 3, 4
STATUS_SHIPPED, STATUS_DELIVERED, STATUS_CANCELLED, STATUS_RETURNED = 5, 6, 7, 8
MELI_SHIPPED_READY_SUBSTATUSES = {
    "authorized_by_carrier", "dropped_off", "in_hub", "in_transit", "picked_up",
}
MELI_RETURN_IN_TRANSIT_SUBSTATUSES = {
    "picked_up_for_return", "returned_to_agency", "returned_to_hub",
    "returning_to_hub", "returning_to_sender", "returning_to_warehouse",
    "soon_to_be_returned",
}
MELI_RETURN_COMPLETED_SUBSTATUSES = {"returned", "returned_to_warehouse"}
MELI_RETURN_IN_PROGRESS_STATUSES = {
    "label_generated", "pending", "pending_delivered", "pending_expiration",
    "pending_failure", "scheduled", "shipped",
}
SHOPEE_RETURN_STATES = {
    "return", "returned", "returning", "returning_to_sender",
    "returned_to_sender", "return_to_sender", "return_completed",
    "refund", "refunded", "partial_refund", "partially_refunded",
    "refund_update", "return_update", "to_return",
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

def _has_explicit_return_state(*values: Any, states: set[str]) -> bool:
    tokens = set()
    for value in values:
        tokens.update(_state_tokens(value))
    return bool(tokens & states)

def _history_date(history: Any, field: str) -> str | None:
    if not isinstance(history, dict):
        return None
    return _timestamp(history.get(field))

def _return_payload(detail: dict, order: dict) -> dict:
    direct = detail.get("return")
    if isinstance(direct, dict):
        return direct
    rows = detail.get("returns")
    if isinstance(rows, list):
        return next((row for row in rows if isinstance(row, dict)), {})
    order_request = order.get("order_request")
    if isinstance(order_request, dict) and isinstance(order_request.get("return"), dict):
        return order_request["return"]
    return {}

def _is_partial_return(return_detail: dict, order_status: str | None) -> bool:
    subtype = _lower(return_detail.get("subtype"))
    if subtype == "return_total":
        return False
    if subtype == "return_partial" or order_status == "partially_refunded":
        return True
    orders = return_detail.get("orders")
    if not isinstance(orders, list):
        return False
    return any(
        _lower(row.get("context_type")) in {"partial", "incomplete"}
        for row in orders if isinstance(row, dict)
    )

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
        return previous
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
    effective_payment = next(
        (
            row for row in payments
            if isinstance(row, dict) and _lower(row.get("status")) == payment_status
        ),
        {},
    )
    payment_status_detail = _lower(effective_payment.get("status_detail"))
    shipping_status = _lower(shipment.get("status"))
    shipping_substatus = _lower(shipment.get("substatus"))
    status_history = shipment.get("status_history")
    shipped_before = (
        shipping_status in {"shipped", "delivered", "not_delivered"}
        or shipping_substatus in MELI_SHIPPED_READY_SUBSTATUSES
        or bool(
            shipment.get("date_shipped")
            or _history_date(status_history, "date_shipped")
        )
    )
    return_detail = _return_payload(detail, order)
    return_status = _lower(return_detail.get("status"))
    return_money_status = _lower(return_detail.get("status_money"))
    partial_return = _is_partial_return(return_detail, order_status)
    return_completed = (
        not partial_return
        and (
            return_status == "delivered"
            or return_money_status == "refunded"
            or shipping_substatus in MELI_RETURN_COMPLETED_SUBSTATUSES
            or bool(_history_date(status_history, "date_returned"))
        )
    )
    return_in_progress = (
        not partial_return
        and (
            return_status in MELI_RETURN_IN_PROGRESS_STATUSES
            or shipping_substatus in MELI_RETURN_IN_TRANSIT_SUBSTATUSES
        )
    )
    full_payment_reversal = (
        payment_status == "refunded"
        or (payment_status == "charged_back" and payment_status_detail == "settled")
    )

    if return_completed:
        stage, target, reason = "returned", STATUS_RETURNED, "explicit_return_completed"
    elif full_payment_reversal:
        stage, target = (
            ("returned", STATUS_RETURNED)
            if shipped_before
            else ("cancelled", STATUS_CANCELLED)
        )
        reason = (
            "full_payment_reversal_after_shipping"
            if shipped_before
            else "full_payment_reversal_before_shipping"
        )
    elif partial_return:
        if shipping_status == "delivered":
            target = STATUS_DELIVERED
        elif shipping_status == "shipped" or shipping_substatus in MELI_SHIPPED_READY_SUBSTATUSES:
            target = STATUS_SHIPPED
        elif shipping_status in {"to_be_shipped", "handling", "ready_to_ship"}:
            target = STATUS_PAID
        else:
            target = STATUS_PAID if order_status in {"confirmed", "paid", "partially_refunded"} else None
        stage, reason = "partially_refunded", "partial_return_does_not_close_order"
    elif return_in_progress:
        target = STATUS_SHIPPED if shipped_before else STATUS_READY
        stage, reason = "return_in_progress", "explicit_return_not_completed"
    elif shipping_status == "delivered":
        stage, target, reason = "delivered", STATUS_DELIVERED, "shipment_delivered"
    elif shipping_status == "shipped" or (
        shipping_status == "ready_to_ship"
        and shipping_substatus in MELI_SHIPPED_READY_SUBSTATUSES
    ):
        stage, target, reason = "shipped", STATUS_SHIPPED, "shipment_shipped"
    elif shipping_status == "not_delivered":
        stage, target, reason = "shipping_exception", STATUS_SHIPPED, "shipment_not_delivered"
    elif order_status in {"cancelled", "canceled", "invalid"}:
        stage, target, reason = "cancelled", STATUS_CANCELLED, "order_cancelled"
    elif order_status == "pending_cancel":
        stage, target, reason = "cancellation_pending", None, "order_cancellation_pending"
    elif shipping_status in {"to_be_shipped", "handling", "ready_to_ship"}:
        stage, target, reason = "paid_preparation", STATUS_PAID, "shipment_requires_processing"
    elif shipping_status in {"cancelled", "canceled"}:
        stage, target, reason = "shipment_cancelled", None, "shipment_is_not_order_cancellation"
    elif payment_status == "charged_back":
        stage, target, reason = "chargeback_pending", None, "chargeback_not_final"
    elif (
        payment_status in {"approved", "authorized"}
        or order_status == "paid"
        or shipping_status == "handling"
    ):
        stage, target, reason = "paid_preparation", STATUS_PAID, "payment_approved"
    elif payment_status in {"pending", "in_process"} or order_status in {
        "confirmed", "opened", "payment_required", "payment_in_process", "partially_paid",
    }:
        stage, target, reason = "awaiting_payment", STATUS_PENDING, "payment_pending"
    elif payment_status == "rejected":
        stage, target, reason = "awaiting_payment", STATUS_PENDING, "payment_rejected_order_not_cancelled"
    else:
        stage, target, reason = "unknown", None, "unmapped_provider_state"

    observed_at = _latest_timestamp(
        return_detail.get("last_updated"), shipment.get("last_updated"),
        order.get("last_updated"), webhook.get("sent"), webhook.get("received")
    )
    return MarketplaceLifecycle(
        order_status, payment_status, shipping_status, shipping_substatus,
        stage, target, observed_at, reason
    )

def resolve_shopee(detail: dict, webhook: dict | None = None) -> MarketplaceLifecycle:
    webhook = webhook or {}
    raw = detail.get("raw") if isinstance(detail.get("raw"), dict) else {}
    order_status = (_value(detail.get("order_status") or raw.get("order_status")) or "").upper() or None
    return_status = _value(detail.get("return_status") or detail.get("refund_status") or raw.get("return_status") or raw.get("refund_status") or webhook.get("return_status") or webhook.get("refund_status"))
    event_type = _value(webhook.get("event") or webhook.get("event_type") or webhook.get("code") or webhook.get("type"))
    if order_status == "TO_RETURN" or _has_explicit_return_state(return_status, event_type, states=SHOPEE_RETURN_STATES):
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
