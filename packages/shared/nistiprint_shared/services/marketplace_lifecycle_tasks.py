"""Lifecycle effect delivery and historical reconciliation tasks."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_repository import canonical_order_repository
from nistiprint_shared.services.marketplace_lifecycle_service import (
    resolve_mercadolivre,
    resolve_shopee,
)
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)

STATUS_EM_ABERTO = 1
STATUS_EM_ANDAMENTO = 2
BACKFILL_ACTIVE_STATUS_IDS = (
    STATUS_EM_ABERTO,
    STATUS_EM_ANDAMENTO,
)


def process_pending_effects(limit: int = 100) -> dict:
    rows = (
        supabase_db.table("marketplace_order_effects")
        .select("id")
        .eq("status", "pending")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    processed, failed = 0, 0
    for row in rows:
        try:
            supabase_db.rpc(
                "process_marketplace_order_effect",
                {"p_effect_id": row["id"]},
            ).execute()
            processed += 1
        except Exception as exc:
            failed += 1
            logger.exception("Failed marketplace lifecycle effect id=%s", row.get("id"))
            (
                supabase_db.table("marketplace_order_effects")
                .update({
                    "attempt_count": row.get("attempt_count", 0) + 1,
                    "last_error": str(exc)[:4000],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", row["id"])
                .execute()
            )
    return {"status": "success", "processed": processed, "failed": failed}


def reconcile_marketplace_lifecycle(
    *,
    dry_run: bool = True,
    days: int = 60,
    limit: int = 100,
    offset: int = 0,
    projection_enabled: bool | None = None,
) -> dict:
    rows = (
        supabase_db.table("pedidos")
        .select("id,numero_pedido,marketplace_module_id,marketplace_order_id,marketplace_integration_id,situacao_pedido_id,erp_order_number,bling_order_number,updated_at")
        .in_("marketplace_module_id", ["shopee", "mercadolivre"])
        .in_("situacao_pedido_id", list(BACKFILL_ACTIVE_STATUS_IDS))
        .order("id")
        .range(offset, offset + limit - 1)
        .execute()
        .data
        or []
    )
    from nistiprint_shared.services.marketplace_webhook_ingest_service import (
        MarketplaceWebhookIngestService,
    )

    ingest = MarketplaceWebhookIngestService()
    compared, failed = 0, []
    if dry_run:
        effective_projection_enabled = False
    elif projection_enabled is not None:
        effective_projection_enabled = bool(projection_enabled)
    else:
        effective_projection_enabled = (
            str(os.getenv("MARKETPLACE_LIFECYCLE_PROJECTION_ENABLED", "false")).lower()
            in ("1", "true", "yes", "on")
        )
    for row in rows:
        try:
            integration_rows = (
                supabase_db.table("installed_integrations")
                .select("*")
                .eq("id", row["marketplace_integration_id"])
                .limit(1)
                .execute()
                .data
                or []
            )
            if not integration_rows:
                raise RuntimeError("marketplace integration not found")
            source = row["marketplace_module_id"]
            order_id = str(row["marketplace_order_id"])
            if source == "shopee":
                detail = ingest._fetch_shopee_detail(integration_rows[0], order_id)
                lifecycle = resolve_shopee(detail, {"event_type": "backfill"})
            else:
                detail = ingest._fetch_meli_detail(integration_rows[0], order_id)
                lifecycle = resolve_mercadolivre(detail, {"topic": "backfill"})
            if detail.get("error"):
                raise RuntimeError(detail["error"])
            canonical_order_repository.apply_marketplace_event(
                {
                    "marketplace_module_id": source,
                    "marketplace_order_id": order_id,
                    "marketplace_integration_id": row["marketplace_integration_id"],
                    "ingest_source": source,
                },
                lifecycle_event={
                    **lifecycle.to_event(),
                    "provider_event_id": (
                        f"backfill:{source}:{order_id}:{lifecycle.observed_at or 'current'}"
                    ),
                    "backfill": True,
                    "dry_run": dry_run,
                },
                projection_enabled=effective_projection_enabled,
            )
            if not dry_run and str(row.get("numero_pedido") or "").upper().startswith("SHOPEE-"):
                real_erp_number = str(row.get("erp_order_number") or "").strip()
                if real_erp_number.upper().startswith("SHOPEE-"):
                    real_erp_number = ""
                update = {
                    "numero_pedido": real_erp_number or str(row["id"]),
                }
                if str(row.get("erp_order_number") or "").upper().startswith("SHOPEE-"):
                    update["erp_order_number"] = None
                if str(row.get("bling_order_number") or "").upper().startswith("SHOPEE-"):
                    update["bling_order_number"] = None
                (
                    supabase_db.table("pedidos")
                    .update(update)
                    .eq("id", row["id"])
                    .execute()
                )
            compared += 1
        except Exception as exc:
            logger.exception("Lifecycle backfill failed pedido_id=%s", row.get("id"))
            failed.append({"pedido_id": row.get("id"), "error": str(exc)})
    return {
        "status": "success",
        "dry_run": dry_run,
        "compared": compared,
        "failed": failed,
        "next_offset": offset + len(rows),
        "has_more": len(rows) == limit,
        "projection_enabled": effective_projection_enabled,
    }


@shared_task(name="nistiprint_shared.services.marketplace_lifecycle_tasks.process_pending_effects")
@log_task_execution(task_type="PEDIDO", task_name="process_pending_effects")
def process_pending_effects_task(limit: int = 100):
    return process_pending_effects(limit=limit)


@shared_task(name="nistiprint_shared.services.marketplace_lifecycle_tasks.reconcile_marketplace_lifecycle")
@log_task_execution(task_type="PEDIDO", task_name="reconcile_marketplace_lifecycle")
def reconcile_marketplace_lifecycle_task(
    dry_run: bool = True,
    days: int = 60,
    limit: int = 100,
    offset: int = 0,
    projection_enabled: bool | None = None,
    continue_batches: bool = True,
):
    result = reconcile_marketplace_lifecycle(
        dry_run=dry_run,
        days=days,
        limit=limit,
        offset=offset,
        projection_enabled=projection_enabled,
    )
    if continue_batches and result.get("has_more"):
        next_task = reconcile_marketplace_lifecycle_task.apply_async(
            kwargs={
                "dry_run": dry_run,
                "days": days,
                "limit": limit,
                "offset": result["next_offset"],
                "projection_enabled": projection_enabled,
                "continue_batches": True,
            },
            countdown=10,
        )
        result["next_task_id"] = next_task.id
    return result

