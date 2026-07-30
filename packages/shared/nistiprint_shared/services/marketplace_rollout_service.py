"""Provider/integration rollout controls for marketplace lifecycle adapters."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from nistiprint_shared.services.marketplace_contracts import CanonicalOrderSnapshot
from nistiprint_shared.services.marketplace_lifecycle_service import (
    MarketplaceLifecycle,
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_SHIPPED,
    project_operational_status,
    resolve_mercadolivre,
    resolve_shopee,
)


ROLLOUT_MODES = {"legacy", "shadow", "active"}


def _env_key(provider: str, suffix: str) -> str:
    normalized = str(provider).strip().upper().replace("-", "_")
    return f"MARKETPLACE_ADAPTER_{suffix}_{normalized}"


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MarketplaceRolloutDecision:
    mode: str
    lifecycle: MarketplaceLifecycle
    active_lifecycle: MarketplaceLifecycle
    legacy_lifecycle: MarketplaceLifecycle
    diverged: bool
    regression: bool

    def comparison(self) -> dict:
        return {
            "mode": self.mode,
            "diverged": self.diverged,
            "regression": self.regression,
            "active": {
                "lifecycle_stage": self.active_lifecycle.lifecycle_stage,
                "target_situacao_pedido_id": self.active_lifecycle.target_situacao_pedido_id,
                "reason": self.active_lifecycle.reason,
            },
            "legacy": {
                "lifecycle_stage": self.legacy_lifecycle.lifecycle_stage,
                "target_situacao_pedido_id": self.legacy_lifecycle.target_situacao_pedido_id,
                "reason": self.legacy_lifecycle.reason,
            },
        }


class MarketplaceRolloutService:
    def mode_for(self, provider: str, integration: dict | None = None) -> str:
        integration = integration or {}
        config = integration.get("config") or {}
        provider_config = (config.get("marketplace_adapter_rollout") or {}).get(provider) or {}
        configured = (
            provider_config.get("mode")
            or config.get("marketplace_adapter_mode")
            or os.getenv(_env_key(provider, "MODE"), "shadow")
        )
        mode = str(configured).strip().lower()
        if mode not in ROLLOUT_MODES:
            mode = "legacy"

        rollback_requested = _truthy(
            provider_config.get("rollback")
            or config.get("marketplace_adapter_rollback")
            or os.getenv(_env_key(provider, "ROLLBACK"))
        )
        rollback_until = _parse_datetime(
            provider_config.get("rollback_until")
            or config.get("marketplace_adapter_rollback_until")
            or os.getenv(_env_key(provider, "ROLLBACK_UNTIL"))
        )
        if rollback_requested and (
            rollback_until is None or datetime.now(timezone.utc) <= rollback_until
        ):
            return "legacy"

        active_ids_raw = (
            provider_config.get("active_integration_ids")
            or os.getenv(_env_key(provider, "ACTIVE_INTEGRATION_IDS"))
        )
        if mode == "active" and active_ids_raw:
            if isinstance(active_ids_raw, (list, tuple, set)):
                active_ids = {str(value).strip() for value in active_ids_raw}
            else:
                active_ids = {
                    value.strip() for value in str(active_ids_raw).split(",") if value.strip()
                }
            if str(integration.get("id") or "") not in active_ids:
                return "shadow"
        return mode

    def normalize(
        self,
        provider: str,
        snapshot: CanonicalOrderSnapshot,
        event: dict,
        integration: dict | None = None,
    ) -> MarketplaceRolloutDecision:
        provider = str(provider).strip().lower()
        if provider == "shopee":
            active = resolve_shopee(snapshot.raw, event)
            legacy = self._legacy_shopee(snapshot.raw, event)
        elif provider == "mercadolivre":
            active = resolve_mercadolivre(snapshot.raw, event)
            legacy = self._legacy_mercadolivre(snapshot.raw, event)
        else:
            raise ValueError(f"provider sem rollout de marketplace: {provider}")

        mode = self.mode_for(provider, integration)
        chosen = active if mode == "active" else legacy
        diverged = (
            active.lifecycle_stage != legacy.lifecycle_stage
            or active.target_situacao_pedido_id != legacy.target_situacao_pedido_id
        )
        regression = (
            legacy.target_situacao_pedido_id is not None
            and (
                active.target_situacao_pedido_id is None
                or project_operational_status(
                    legacy.target_situacao_pedido_id,
                    active.target_situacao_pedido_id,
                ) != active.target_situacao_pedido_id
            )
        )
        return MarketplaceRolloutDecision(
            mode, chosen, active, legacy, diverged, regression
        )

    @staticmethod
    def _legacy_shopee(detail: dict, event: dict) -> MarketplaceLifecycle:
        active = resolve_shopee(detail, event)
        mapping = {
            "UNPAID": ("awaiting_payment", STATUS_PENDING),
            "INVOICE_PENDING": ("paid_preparation", STATUS_PAID),
            "READY_TO_SHIP": ("paid_preparation", STATUS_PAID),
            "RETRY_SHIP": ("paid_preparation", STATUS_PAID),
            "PROCESSED": ("documentation_ready", STATUS_READY),
            "SHIPPED": ("shipped", STATUS_SHIPPED),
            "TO_CONFIRM_RECEIVE": ("shipped", STATUS_SHIPPED),
            "COMPLETED": ("delivered", STATUS_DELIVERED),
            "CANCELLED": ("cancelled", STATUS_CANCELLED),
        }
        stage, target = mapping.get(active.order_status or "", ("unknown", None))
        return replace(
            active,
            lifecycle_stage=stage,
            target_situacao_pedido_id=target,
            reason=f"legacy_shopee_order_status:{active.order_status or 'missing'}",
        )

    @staticmethod
    def _legacy_mercadolivre(detail: dict, event: dict) -> MarketplaceLifecycle:
        active = resolve_mercadolivre(detail, event)
        payment = active.payment_status
        shipping = active.shipping_status
        if payment in {"rejected", "refunded", "charged_back"}:
            stage, target = "cancelled", STATUS_CANCELLED
        elif shipping in {"cancelled", "canceled"}:
            stage, target = "cancelled", STATUS_CANCELLED
        elif shipping == "delivered":
            stage, target = "delivered", STATUS_DELIVERED
        elif shipping in {"shipped", "not_delivered"}:
            stage, target = "shipped", STATUS_SHIPPED
        elif shipping in {"to_be_shipped", "handling", "ready_to_ship"}:
            stage, target = "documentation_ready", STATUS_READY
        elif payment in {"approved", "authorized"}:
            stage, target = "paid_preparation", STATUS_PAID
        elif payment in {"pending", "in_process"}:
            stage, target = "awaiting_payment", STATUS_PENDING
        else:
            stage, target = "unknown", None
        return replace(
            active,
            lifecycle_stage=stage,
            target_situacao_pedido_id=target,
            reason="legacy_marketplace_status_precedence",
        )


marketplace_rollout_service = MarketplaceRolloutService()
