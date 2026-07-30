"""Typed contracts shared by marketplace webhook adapters and API drivers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Generic, Literal, TypeVar


ResourceType = Literal[
    "order",
    "shipment",
    "payment",
    "collection",
    "pack",
    "return",
    "chat",
    "verification",
    "unknown",
]

T = TypeVar("T")


@dataclass(frozen=True)
class MarketplaceResourceRef:
    provider: str
    resource_type: ResourceType
    resource_id: str
    resource_path: str
    account_id: str | None = None
    provider_event_id: str | None = None
    occurred_at: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        provider = str(self.provider or "").strip().lower()
        resource_id = str(self.resource_id or "").strip()
        resource_path = str(self.resource_path or "").strip()
        if not provider:
            raise ValueError("marketplace provider ausente")
        if not resource_id:
            raise ValueError("marketplace resource_id ausente")
        if not resource_path.startswith("/"):
            raise ValueError("marketplace resource_path invalido")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "resource_path", resource_path)


@dataclass(frozen=True)
class ProviderCallResult(Generic[T]):
    ok: bool
    value: T | None = None
    provider: str | None = None
    resource_type: ResourceType | None = None
    resource_id: str | None = None
    status_code: int | None = None
    provider_code: str | None = None
    error_type: str | None = None
    message: str | None = None
    retryable: bool = False
    retry_after: float | None = None
    partial: bool = False
    details: Any = None

    def to_legacy(self) -> Any:
        """Keep existing public driver functions backward compatible."""
        if self.ok:
            return self.value
        result = {
            "error": self.message or self.error_type or "Erro na API do marketplace",
            "error_type": self.error_type or "provider_api_error",
            "retryable": bool(self.retryable),
        }
        for key, value in (
            ("status_code", self.status_code),
            ("code", self.provider_code),
            ("retry_after", self.retry_after),
            ("details", self.details),
            ("resource_type", self.resource_type),
            ("resource_id", self.resource_id),
        ):
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class WebhookResolution:
    provider: str
    classification: str
    status: str
    resources: tuple[MarketplaceResourceRef, ...] = ()
    resolved_order_ids: tuple[str, ...] = ()
    trace: tuple[dict[str, Any], ...] = ()
    error_type: str | None = None
    message: str | None = None
    retryable: bool = False
    retry_after: float | None = None

    @property
    def primary_resource(self) -> MarketplaceResourceRef | None:
        return self.resources[0] if self.resources else None

    @property
    def primary_order_id(self) -> str | None:
        return self.resolved_order_ids[0] if self.resolved_order_ids else None

    def with_orders(
        self,
        order_ids: list[str] | tuple[str, ...],
        *,
        status: str = "resolved",
        trace: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> "WebhookResolution":
        unique = tuple(dict.fromkeys(str(value) for value in order_ids if str(value)))
        return WebhookResolution(
            provider=self.provider,
            classification=self.classification,
            status=status,
            resources=self.resources,
            resolved_order_ids=unique,
            trace=(*self.trace, *tuple(trace)),
        )


@dataclass(frozen=True)
class CanonicalOrderSnapshot:
    provider: str
    order_id: str
    order_status: str | None = None
    payment_status: str | None = None
    shipping_status: str | None = None
    return_status: str | None = None
    customer: dict[str, Any] = field(default_factory=dict)
    items: tuple[dict[str, Any], ...] = ()
    logistics: dict[str, Any] = field(default_factory=dict)
    timestamps: dict[str, Any] = field(default_factory=dict)
    total: float | None = None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
