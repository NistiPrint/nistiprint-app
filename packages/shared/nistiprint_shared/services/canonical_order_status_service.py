"""Resolucao pontual de status externo -> situacao interna.

Fachada sobre `order_status_lexicon`. Existe para os chamadores que tem um unico
status em maos (telas de configuracao, reprocessamento manual, backfill) e nao um
snapshot completo do pedido.

Quando ha snapshot, o caminho correto e
`marketplace_lifecycle_service.resolve_*`, que considera todos os dominios.

O fallback hardcoded que existia aqui foi removido: ausencia de mapeamento agora
produz `unmapped` de forma visivel, em vez de um palpite silencioso.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nistiprint_shared.services.order_status_decision import effective_payment_status
from nistiprint_shared.services.order_status_lexicon import (
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_RETURNED,
    STATUS_SHIPPED,
    LexiconResolver,
    lexicon,
)

logger = logging.getLogger(__name__)

STATUS_EM_ABERTO = STATUS_PENDING
STATUS_EM_ANDAMENTO = STATUS_PAID
STATUS_PRONTO_ENVIO = 4
STATUS_ENVIADO = STATUS_SHIPPED
STATUS_ENTREGUE = STATUS_DELIVERED
STATUS_CANCELADO = STATUS_CANCELLED
STATUS_DEVOLVIDO = STATUS_RETURNED


@dataclass(frozen=True)
class StatusResolution:
    internal_situacao_pedido_id: int | None
    module_id: str
    status_domain: str | None
    external_status_id: str | None
    source: str
    lifecycle_stage: str | None = None


def _normalize(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    return normalized or None


class CanonicalOrderStatusService:
    def __init__(self, resolver: LexiconResolver | None = None) -> None:
        self._resolver = resolver or lexicon

    def resolve(
        self,
        module_id: str,
        external_status_id: Any,
        *,
        status_domain: str = "order",
        integration_id: int | None = None,
    ) -> StatusResolution:
        module = (_normalize(module_id) or "").lower()
        domain = (_normalize(status_domain) or "order").lower()
        status = _normalize(external_status_id)
        if not module or not status:
            return StatusResolution(None, module, domain, status, "empty")

        entry = self._resolver.lookup(
            module, domain, status, integration_id=integration_id
        )
        if entry is None:
            logger.info(
                "[status-lexicon] sem mapeamento module=%s domain=%s status=%s",
                module, domain, status,
            )
            return StatusResolution(None, module, domain, status, "unmapped")

        return StatusResolution(
            entry.situacao, module, domain, status, entry.source, entry.stage
        )

    def resolve_shopee(
        self, order_status: Any, *, integration_id: int | None = None
    ) -> StatusResolution:
        return self.resolve(
            "shopee", order_status, status_domain="order", integration_id=integration_id
        )

    def resolve_bling(
        self, bling_situacao_id: Any, *, integration_id: int | None = None
    ) -> StatusResolution:
        return self.resolve(
            "bling", bling_situacao_id, status_domain="order",
            integration_id=integration_id,
        )

    def resolve_mercadolivre(
        self,
        *,
        payment_status: Any = None,
        shipping_status: Any = None,
        integration_id: int | None = None,
    ) -> StatusResolution:
        """Resolve com um status por dominio, aplicando a precedencia da §7.1.

        Logistica vence pagamento quando ambos sao conhecidos: descreve o fato
        mais recente do mundo fisico.
        """
        candidates = [
            ("shipping", _normalize(shipping_status)),
            ("payment", _normalize(payment_status)),
        ]
        best: StatusResolution | None = None
        best_rank = -1
        for domain, status in candidates:
            if not status:
                continue
            entry = self._resolver.lookup(
                "mercadolivre", domain, status, integration_id=integration_id
            )
            if entry is None:
                if best is None:
                    best = StatusResolution(
                        None, "mercadolivre", domain, status, "unmapped"
                    )
                continue
            if entry.rank > best_rank:
                best_rank = entry.rank
                best = StatusResolution(
                    entry.situacao, "mercadolivre", domain, status,
                    entry.source, entry.stage,
                )
        if best is None:
            return StatusResolution(None, "mercadolivre", None, None, "empty")
        return best

    @staticmethod
    def effective_payment_status(payments: Any) -> str | None:
        return effective_payment_status(payments)


canonical_order_status_service = CanonicalOrderStatusService()
