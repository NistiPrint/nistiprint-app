"""Provider-aware marketplace lifecycle normalization.

Fachada fina sobre o pipeline canonico de tres camadas descrito em
`docs/specs/03-contracts/canonizacao-status-pedido.md`:

    observer (driver)  ->  lexico (dado)  ->  decisao (unica)  ->  projecao

Este modulo existe para preservar a assinatura publica que o ingest, o rollout e
as tasks de backfill ja consomem. Toda a regra vive em `order_status_observers`,
`order_status_lexicon` e `order_status_decision`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from nistiprint_shared.services.order_status_decision import (
    CanonicalDecision,
    DecisionContext,
    DomainObservation,
    decide,
    latest_timestamp,
    project_operational_status,
)
from nistiprint_shared.services.order_status_lexicon import (
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_PRODUCED,
    STATUS_RETURNED,
    STATUS_SHIPPED,
    LexiconResolver,
)
from nistiprint_shared.services.order_status_observers import (
    observe_bling,
    observe_mercadolivre,
    observe_shopee,
)

#: Aliases historicos mantidos para nao quebrar importadores existentes.
STATUS_IN_PRODUCTION = STATUS_PRODUCED
STATUS_READY = 4

__all__ = [
    "MarketplaceLifecycle",
    "DomainObservation",
    "DecisionContext",
    "STATUS_PENDING",
    "STATUS_PAID",
    "STATUS_IN_PRODUCTION",
    "STATUS_PRODUCED",
    "STATUS_READY",
    "STATUS_SHIPPED",
    "STATUS_DELIVERED",
    "STATUS_CANCELLED",
    "STATUS_RETURNED",
    "project_operational_status",
    "resolve_shopee",
    "resolve_mercadolivre",
    "resolve_bling",
    "latest_timestamp",
]


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


def _to_lifecycle(decision: CanonicalDecision) -> MarketplaceLifecycle:
    return MarketplaceLifecycle(
        order_status=decision.order_status,
        payment_status=decision.payment_status,
        # A Shopee nao expoe dominio logistico proprio: o substatus carrega o
        # estado de devolucao, como o contrato anterior ja fazia.
        shipping_status=decision.shipping_status,
        shipping_substatus=decision.shipping_substatus or decision.return_status,
        lifecycle_stage=decision.lifecycle_stage,
        target_situacao_pedido_id=decision.target_situacao_pedido_id,
        observed_at=decision.observed_at,
        reason=decision.reason,
    )


def _resolve(
    provider: str,
    observations: list[DomainObservation],
    context: DecisionContext,
    *,
    fallback_observed_at: Any = None,
    resolver: LexiconResolver | None = None,
    integration_id: int | None = None,
) -> MarketplaceLifecycle:
    decision = decide(
        provider,
        observations,
        context=context,
        resolver=resolver,
        integration_id=integration_id,
    )
    if decision.observed_at is None and fallback_observed_at is not None:
        decision = CanonicalDecision(
            **{
                **decision.__dict__,
                "observed_at": latest_timestamp(fallback_observed_at),
            }
        )
    return _to_lifecycle(decision)


def resolve_shopee(
    detail: dict,
    webhook: dict | None = None,
    *,
    resolver: LexiconResolver | None = None,
    integration_id: int | None = None,
) -> MarketplaceLifecycle:
    observations, context = observe_shopee(detail, webhook)
    webhook = webhook or {}
    return _resolve(
        "shopee", observations, context,
        fallback_observed_at=webhook.get("timestamp") or webhook.get("update_time"),
        resolver=resolver, integration_id=integration_id,
    )


def resolve_mercadolivre(
    detail: dict,
    webhook: dict | None = None,
    *,
    resolver: LexiconResolver | None = None,
    integration_id: int | None = None,
) -> MarketplaceLifecycle:
    observations, context = observe_mercadolivre(detail, webhook)
    webhook = webhook or {}
    return _resolve(
        "mercadolivre", observations, context,
        fallback_observed_at=webhook.get("sent") or webhook.get("received"),
        resolver=resolver, integration_id=integration_id,
    )


def resolve_bling(
    payload: dict,
    webhook: dict | None = None,
    *,
    resolver: LexiconResolver | None = None,
    integration_id: int | None = None,
) -> MarketplaceLifecycle:
    observations, context = observe_bling(payload, webhook)
    return _resolve(
        "bling", observations, context,
        resolver=resolver, integration_id=integration_id,
    )
