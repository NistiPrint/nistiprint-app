"""Read-only promotion checks for marketplace adapter shadow rollouts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class MarketplaceRolloutAuditService:
    def evaluate(
        self,
        provider: str,
        integration_id: int,
        *,
        shadow_started_at: str | datetime,
        minimum_hours: int = 72,
        minimum_events: int = 500,
    ) -> dict[str, Any]:
        started = _utc(shadow_started_at)
        now = datetime.now(timezone.utc)
        rows = (
            supabase_db.table("marketplace_order_transitions")
            .select("id,created_at,provider_state")
            .eq("module_id", str(provider).strip().lower())
            .contains("provider_state", {
                "adapter_mode": "shadow",
                "marketplace_integration_id": integration_id,
            })
            .gte("created_at", started.isoformat())
            .order("id")
            .limit(max(5000, minimum_events))
            .execute()
            .data
            or []
        )
        regressions = [
            row["id"]
            for row in rows
            if ((row.get("provider_state") or {}).get("shadow_comparison") or {}).get(
                "regression"
            )
        ]
        violations = (
            supabase_db.table("webhook_events")
            .select("id")
            .eq("source", str(provider).strip().lower())
            .eq("resolution_status", "endpoint_type_violation")
            .gte("received_at", started.isoformat())
            .limit(1)
            .execute()
            .data
            or []
        )
        elapsed_hours = max(0.0, (now - started).total_seconds() / 3600)
        ready = (
            elapsed_hours >= minimum_hours
            and len(rows) >= minimum_events
            and not regressions
            and not violations
        )
        return {
            "provider": provider,
            "marketplace_integration_id": integration_id,
            "ready": ready,
            "elapsed_hours": round(elapsed_hours, 2),
            "minimum_hours": minimum_hours,
            "event_count": len(rows),
            "minimum_events": minimum_events,
            "canonical_regression_count": len(regressions),
            "endpoint_violation_count": len(violations),
            "blocking_reasons": [
                reason
                for condition, reason in (
                    (elapsed_hours < minimum_hours, "minimum_shadow_duration"),
                    (len(rows) < minimum_events, "minimum_event_volume"),
                    (bool(regressions), "canonical_regression"),
                    (bool(violations), "endpoint_type_violation"),
                )
                if condition
            ],
        }


marketplace_rollout_audit_service = MarketplaceRolloutAuditService()
