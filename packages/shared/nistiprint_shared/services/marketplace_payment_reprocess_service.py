"""Controlled replay of unresolved Mercado Livre webhook events.

Originalmente escrito so para `payments`, o replay foi parametrizado por topico
quando o header `x-format-new` quebrou a resolucao de `shipments` (o formato novo
de /shipments/{id} deixou de expor order_id/pack_id) e centenas de eventos
morreram como `failed_terminal`, travando pedidos em "Em Andamento".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.reliable_ingest_queue import (
    build_envelope,
    publish_envelope,
)


ELIGIBLE_STATUSES = (
    "failed",
    "failed_terminal",
    "dead_letter",
    "manual_intervention",
    "pending_retry",
)
PAYMENT_RESOURCE_TYPES = {"payment", "collection"}
SHIPMENT_RESOURCE_TYPES = {"shipment"}

# Prefixo do provider_resource -> resource_type, usado quando o evento antigo
# nao gravou provider_resource_type.
_RESOURCE_PREFIXES = {
    "/payments/": "payment",
    "/collections/": "collection",
    "/shipments/": "shipment",
}


def _resource_type(row: dict, allowed: set[str] = PAYMENT_RESOURCE_TYPES) -> str | None:
    typed = str(row.get("provider_resource_type") or "").strip().lower()
    if typed in allowed:
        return typed
    resource = str(row.get("provider_resource") or "").strip().lower()
    for prefix, kind in _RESOURCE_PREFIXES.items():
        if resource.startswith(prefix) and kind in allowed:
            return kind
    return None


class MarketplaceEventReprocessService:
    """Replay controlado de webhooks do Mercado Livre por topico."""

    def __init__(
        self,
        *,
        topic: str = "payments",
        resource_types: set[str] = PAYMENT_RESOURCE_TYPES,
        label: str = "payment",
    ) -> None:
        self.topic = topic
        self.resource_types = set(resource_types)
        self.label = label

    def list_candidates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit or 100), 500))
        rows = (
            supabase_db.table("webhook_events")
            .select(
                "id,source,last_status,raw_payload,received_at,provider_event_id,"
                "provider_topic,provider_resource,provider_resource_type,"
                "provider_resource_id,resolution_status,last_error_type"
            )
            .eq("source", "mercadolivre")
            .eq("provider_topic", self.topic)
            .in_("last_status", list(ELIGIBLE_STATUSES))
            .order("id")
            .limit(capped * 3)
            .execute()
            .data
            or []
        )
        candidates = []
        for row in rows:
            if _resource_type(row, self.resource_types) not in self.resource_types:
                continue
            if not isinstance(row.get("raw_payload"), dict) or not row["raw_payload"]:
                continue
            candidates.append(dict(row))
            if len(candidates) >= capped:
                break
        return candidates

    def reprocess(
        self,
        *,
        dry_run: bool = True,
        limit: int = 100,
        client=None,
    ) -> dict[str, Any]:
        candidates = self.list_candidates(limit=limit)
        if dry_run:
            return {
                "status": "success",
                "dry_run": True,
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "webhook_event_id": row["id"],
                        "resource_type": _resource_type(row, self.resource_types),
                        "resource_id": row.get("provider_resource_id"),
                        "last_status": row.get("last_status"),
                        "last_error_type": row.get("last_error_type"),
                    }
                    for row in candidates
                ],
            }

        queued, failed = [], []
        now = datetime.now(timezone.utc).isoformat()
        for row in candidates:
            event_id = int(row["id"])
            previous_status = str(row.get("last_status") or "")
            try:
                reservation = (
                    supabase_db.table("webhook_events")
                    .update({
                        "last_status": f"{self.label}_reprocess_reserving",
                        "resolution_status": "reprocess_reserving",
                        "last_attempt_at": now,
                    })
                    .eq("id", event_id)
                    .eq("last_status", previous_status)
                    .execute()
                    .data
                    or []
                )
                if not reservation:
                    continue

                envelope = build_envelope(
                    "mercadolivre",
                    row["raw_payload"],
                    event_id=f"{self.label}-reprocess:{event_id}:{now}",
                    received_at=row.get("received_at") or now,
                    provider_delivery_id=row.get("provider_event_id"),
                )
                envelope["webhook_event_id"] = event_id
                envelope["reprocess_requested_at"] = now
                publish_envelope(envelope, client=client)
                (
                    supabase_db.table("webhook_events")
                    .update({
                        "last_status": f"{self.label}_reprocess_queued",
                        "resolution_status": "reprocess_queued",
                        "attempt_count": 0,
                        "next_attempt_after": None,
                        "processing_started_at": None,
                        "processing_correlation_id": None,
                        "last_error_type": None,
                        "last_error_message": None,
                    })
                    .eq("id", event_id)
                    .execute()
                )
                queued.append(event_id)
            except Exception as exc:
                (
                    supabase_db.table("webhook_events")
                    .update({
                        "last_status": previous_status,
                        "resolution_status": "reprocess_publish_failed",
                        "last_error_type": f"{self.label}_reprocess_publish_failed",
                        "last_error_message": str(exc)[:1000],
                    })
                    .eq("id", event_id)
                    .eq("last_status", f"{self.label}_reprocess_reserving")
                    .execute()
                )
                failed.append({
                    "webhook_event_id": event_id,
                    "error_type": type(exc).__name__,
                })
        return {
            "status": "success" if not failed else "partial_success",
            "dry_run": False,
            "candidate_count": len(candidates),
            "queued": queued,
            "failed": failed,
        }


# Alias mantido para compatibilidade com imports existentes.
MarketplacePaymentReprocessService = MarketplaceEventReprocessService

marketplace_payment_reprocess_service = MarketplaceEventReprocessService(
    topic="payments",
    resource_types=PAYMENT_RESOURCE_TYPES,
    label="payment",
)

marketplace_shipment_reprocess_service = MarketplaceEventReprocessService(
    topic="shipments",
    resource_types=SHIPMENT_RESOURCE_TYPES,
    label="shipment",
)


@shared_task(
    name=(
        "nistiprint_shared.services.marketplace_payment_reprocess_service."
        "reprocess_unresolved_payments"
    )
)
def reprocess_unresolved_payments_task(
    dry_run: bool = True,
    limit: int = 100,
):
    return marketplace_payment_reprocess_service.reprocess(
        dry_run=dry_run,
        limit=limit,
    )


@shared_task(
    name=(
        "nistiprint_shared.services.marketplace_payment_reprocess_service."
        "reprocess_unresolved_shipments"
    )
)
def reprocess_unresolved_shipments_task(
    dry_run: bool = True,
    limit: int = 100,
):
    return marketplace_shipment_reprocess_service.reprocess(
        dry_run=dry_run,
        limit=limit,
    )
