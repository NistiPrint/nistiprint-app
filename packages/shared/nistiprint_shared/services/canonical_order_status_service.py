import logging
from dataclasses import dataclass
from typing import Any, Iterable

from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger(__name__)


STATUS_EM_ABERTO = 1
STATUS_EM_ANDAMENTO = 2
STATUS_PRONTO_ENVIO = 4
STATUS_ENVIADO = 5
STATUS_ENTREGUE = 6
STATUS_CANCELADO = 7
STATUS_DEVOLVIDO = 8


DEFAULT_STATUS_MAPPINGS: dict[tuple[str, str, str], int] = {
    ("bling", "order", "6"): STATUS_EM_ABERTO,
    ("bling", "order", "15"): STATUS_EM_ANDAMENTO,
    ("bling", "order", "24"): STATUS_PRONTO_ENVIO,
    ("bling", "order", "9"): STATUS_ENVIADO,
    ("bling", "order", "12"): STATUS_CANCELADO,
}

MELI_STATUS_PRECEDENCE = (
    ("payment", "rejected"),
    ("payment", "refunded"),
    ("shipping", "cancelled"),
    ("shipping", "delivered"),
    ("shipping", "shipped"),
    ("shipping", "not_delivered"),
    ("shipping", "to_be_shipped"),
    ("shipping", "handling"),
    ("shipping", "ready_to_ship"),
    ("payment", "approved"),
    ("payment", "authorized"),
    ("payment", "in_process"),
    ("payment", "pending"),
)


@dataclass(frozen=True)
class StatusResolution:
    internal_situacao_pedido_id: int | None
    module_id: str
    status_domain: str | None
    external_status_id: str | None
    source: str


def _normalize_module_id(module_id: Any) -> str:
    return str(module_id or "").strip().lower()


def _normalize_domain(status_domain: Any) -> str:
    return str(status_domain or "order").strip().lower()


def _normalize_status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


class CanonicalOrderStatusService:
    def resolve(
        self,
        module_id: str,
        external_status_id: Any,
        *,
        status_domain: str = "order",
        integration_id: int | None = None,
    ) -> StatusResolution:
        module = _normalize_module_id(module_id)
        domain = _normalize_domain(status_domain)
        status = _normalize_status(external_status_id)
        if not module or not status:
            return StatusResolution(None, module, domain, status, "empty")

        mapped = self._resolve_from_db(
            module,
            status,
            status_domain=domain,
            integration_id=integration_id,
        )
        if mapped is not None:
            return StatusResolution(mapped, module, domain, status, "db")

        fallback = DEFAULT_STATUS_MAPPINGS.get((module, domain, status))
        if fallback is None:
            fallback = DEFAULT_STATUS_MAPPINGS.get((module, domain, status.upper()))
        if fallback is None:
            fallback = DEFAULT_STATUS_MAPPINGS.get((module, domain, status.lower()))

        return StatusResolution(fallback, module, domain, status, "fallback" if fallback else "unmapped")

    def resolve_shopee(
        self,
        order_status: Any,
        *,
        integration_id: int | None = None,
    ) -> StatusResolution:
        from nistiprint_shared.services.marketplace_lifecycle_service import resolve_shopee
        status = _normalize_status(order_status)
        lifecycle = resolve_shopee({"order_status": status})
        return StatusResolution(
            lifecycle.target_situacao_pedido_id,
            "shopee",
            "order",
            status,
            "marketplace_lifecycle",
        )

    def resolve_bling(
        self,
        bling_situacao_id: Any,
        *,
        integration_id: int | None = None,
    ) -> StatusResolution:
        return self.resolve("bling", bling_situacao_id, status_domain="order", integration_id=integration_id)

    def resolve_mercadolivre(
        self,
        *,
        payment_status: Any = None,
        shipping_status: Any = None,
        integration_id: int | None = None,
    ) -> StatusResolution:
        from nistiprint_shared.services.marketplace_lifecycle_service import resolve_mercadolivre
        payment = _normalize_status(payment_status)
        shipping = _normalize_status(shipping_status)
        lifecycle = resolve_mercadolivre({
            "order": {"payments": [{"status": payment}]} if payment else {},
            "shipment": {"status": shipping} if shipping else {},
        })
        domain = "shipping" if shipping else ("payment" if payment else None)
        external = shipping or payment
        return StatusResolution(
            lifecycle.target_situacao_pedido_id,
            "mercadolivre",
            domain,
            external,
            "marketplace_lifecycle",
        )

    def _ordered_mercadolivre_statuses(self, statuses: dict[str, str | None]) -> Iterable[tuple[str, str]]:
        used = set()
        for domain, expected in MELI_STATUS_PRECEDENCE:
            actual = statuses.get(domain)
            if actual and actual.lower() == expected:
                used.add((domain, actual))
                yield domain, actual

        for domain, status in statuses.items():
            if status and (domain, status) not in used:
                yield domain, status

    def _resolve_from_db(
        self,
        module_id: str,
        external_status_id: str,
        *,
        status_domain: str,
        integration_id: int | None,
    ) -> int | None:
        for scoped_integration_id in (integration_id, None):
            if scoped_integration_id is None and integration_id is None:
                # Ainda precisamos tentar o escopo global uma vez.
                pass
            try:
                query = (
                    supabase_db.table("integration_status_mappings")
                    .select("internal_situacao_pedido_id")
                    .eq("module_id", module_id)
                    .eq("status_domain", status_domain)
                    .eq("external_status_id", external_status_id)
                    .eq("is_active", True)
                    .limit(1)
                )
                if scoped_integration_id is None:
                    query = query.is_("integration_id", "null")
                else:
                    query = query.eq("integration_id", scoped_integration_id)
                rows = query.execute().data or []
                if not isinstance(rows, list):
                    rows = []
            except Exception as exc:
                logger.debug(
                    "status mapping lookup failed module=%s domain=%s status=%s integration=%s: %s",
                    module_id,
                    status_domain,
                    external_status_id,
                    scoped_integration_id,
                    exc,
                )
                rows = []

            if rows and rows[0].get("internal_situacao_pedido_id"):
                return rows[0]["internal_situacao_pedido_id"]

            if scoped_integration_id is None:
                break

        return None


canonical_order_status_service = CanonicalOrderStatusService()
