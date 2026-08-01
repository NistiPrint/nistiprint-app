"""Provider observers — extracao de fatos, sem regra de negocio.

Camada de driver do contrato em
`docs/specs/03-contracts/canonizacao-status-pedido.md` (§8).

Cada `observe_*` recebe o payload/snapshot que o provider entregou e devolve
observacoes de dominio com o valor **bruto**, mais o contexto factual que a
decisao precisa (houve despacho? o reembolso e parcial?).

Um observer nao importa constante de situacao, nao conhece estagio canonico e
nao decide precedencia. Se precisar de um `if` sobre regra de status, a regra
esta no lugar errado.
"""
from __future__ import annotations

from typing import Any

from nistiprint_shared.services.order_status_decision import (
    DecisionContext,
    DomainObservation,
    effective_payment_status,
)


def _value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    return normalized or None


def _lower(value: Any) -> str | None:
    normalized = _value(value)
    return normalized.lower() if normalized else None


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _obs(
    domain: str,
    status: Any,
    occurred_at: Any = None,
    raw: dict | None = None,
) -> DomainObservation | None:
    normalized = _value(status)
    if not normalized:
        return None
    return DomainObservation(
        domain=domain,  # type: ignore[arg-type]
        external_status_id=normalized,
        provider_occurred_at=_value(occurred_at),
        raw=raw or {},
    )


def _compact(*observations: DomainObservation | None) -> list[DomainObservation]:
    return [obs for obs in observations if obs is not None]


# --------------------------------------------------------------------------- #
# Shopee
# --------------------------------------------------------------------------- #

#: Topicos/eventos de devolucao. Servem apenas para saber *onde procurar* o
#: status de retorno no payload — nunca para inferir que houve devolucao.
_SHOPEE_RETURN_TOPICS = {
    "refund", "refund_update", "return", "return_update", "returns",
}

_SHOPEE_PARTIAL_TOKENS = {"partial_refund", "partially_refunded", "partial"}


def observe_shopee(
    detail: dict,
    webhook: dict | None = None,
) -> tuple[list[DomainObservation], DecisionContext]:
    detail = _dict(detail)
    webhook = _dict(webhook)
    raw = _dict(detail.get("raw"))

    update_time = (
        detail.get("update_time")
        or raw.get("update_time")
        or webhook.get("timestamp")
        or webhook.get("update_time")
    )

    order_status = _value(detail.get("order_status") or raw.get("order_status"))
    if order_status:
        order_status = order_status.upper()

    return_status = _value(
        detail.get("return_status")
        or detail.get("refund_status")
        or raw.get("return_status")
        or raw.get("refund_status")
    )
    if not return_status:
        topic = _lower(
            webhook.get("event")
            or webhook.get("event_type")
            or webhook.get("type")
        )
        if topic in _SHOPEE_RETURN_TOPICS:
            return_status = _value(
                webhook.get("return_status") or webhook.get("refund_status")
            )

    observations = _compact(
        _obs("order", order_status, update_time, {"source": "order_status"}),
        _obs("return", return_status, update_time, {"source": "return_status"}),
    )

    partial = _lower(return_status) in _SHOPEE_PARTIAL_TOKENS
    shipped_at = detail.get("ship_time") or raw.get("ship_time")

    return observations, DecisionContext(
        shipped_at=_value(shipped_at), partial_refund=partial
    )


# --------------------------------------------------------------------------- #
# Mercado Livre
# --------------------------------------------------------------------------- #

_MELI_PARTIAL_CONTEXTS = {"partial", "incomplete"}


def _meli_return_payload(detail: dict, order: dict) -> dict:
    direct = detail.get("return")
    if isinstance(direct, dict):
        return direct
    rows = detail.get("returns")
    if isinstance(rows, list):
        return next((row for row in rows if isinstance(row, dict)), {})
    order_request = _dict(order.get("order_request"))
    return _dict(order_request.get("return"))


def _meli_is_partial(return_detail: dict, order_status: str | None) -> bool:
    subtype = _lower(return_detail.get("subtype"))
    if subtype == "return_total":
        return False
    if subtype == "return_partial" or order_status == "partially_refunded":
        return True
    orders = return_detail.get("orders")
    if not isinstance(orders, list):
        return False
    return any(
        _lower(row.get("context_type")) in _MELI_PARTIAL_CONTEXTS
        for row in orders
        if isinstance(row, dict)
    )


def observe_mercadolivre(
    detail: dict,
    webhook: dict | None = None,
) -> tuple[list[DomainObservation], DecisionContext]:
    detail = _dict(detail)
    webhook = _dict(webhook)
    order = _dict(detail.get("order"))
    shipment = _dict(detail.get("shipment"))
    return_detail = _meli_return_payload(detail, order)
    status_history = _dict(shipment.get("status_history"))

    payments = order.get("payments") if isinstance(order.get("payments"), list) else []
    payment_status = effective_payment_status(payments)
    effective_payment = next(
        (
            row for row in payments
            if isinstance(row, dict) and _lower(row.get("status")) == payment_status
        ),
        {},
    )
    payment_detail = _lower(_dict(effective_payment).get("status_detail"))
    order_updated = order.get("last_updated")
    shipment_updated = shipment.get("last_updated") or order_updated
    return_updated = return_detail.get("last_updated") or order_updated

    observations = _compact(
        _obs("order", order.get("status"), order_updated),
        # §7.2: varias tentativas de pagamento colapsam em um status efetivo
        # antes de virar observacao.
        _obs("payment", payment_status, order_updated),
        # O provider qualifica o status com `status_detail`. Compor os dois e
        # extracao, nao interpretacao: quem decide o que `charged_back:settled`
        # significa continua sendo o lexico.
        _obs(
            "payment_detail",
            f"{payment_status}:{payment_detail}" if payment_status and payment_detail else None,
            order_updated,
        ),
        _obs("shipping", shipment.get("status"), shipment_updated),
        _obs("shipping_substatus", shipment.get("substatus"), shipment_updated),
        _obs("return", return_detail.get("status"), return_updated),
        # `status_money` e um fato de devolucao distinto do andamento logistico.
        _obs("return", return_detail.get("status_money"), return_updated),
    )

    if status_history.get("date_returned"):
        returned = _obs(
            "shipping_substatus", "returned", status_history.get("date_returned")
        )
        if returned is not None:
            observations.append(returned)

    shipped_at = shipment.get("date_shipped") or status_history.get("date_shipped")
    partial = _meli_is_partial(return_detail, _lower(order.get("status")))

    return observations, DecisionContext(
        shipped_at=_value(shipped_at), partial_refund=partial
    )


# --------------------------------------------------------------------------- #
# Bling
# --------------------------------------------------------------------------- #


def observe_bling(
    payload: dict,
    webhook: dict | None = None,
) -> tuple[list[DomainObservation], DecisionContext]:
    """Bling entrega uma observacao de ciclo e uma de identidade/fiscal.

    A segunda vale em qualquer `ingest_origin_mode`; a primeira so projeta quando
    o vinculo autoriza (§7.4).
    """
    payload = _dict(payload)
    webhook = _dict(webhook)
    data = _dict(payload.get("data")) or payload

    situacao = data.get("situacao")
    if isinstance(situacao, dict):
        situacao_id = situacao.get("id")
    else:
        situacao_id = situacao or data.get("situacao_id") or data.get("situacaoId")

    updated_at = (
        data.get("dataAlteracao")
        or data.get("data_alteracao")
        or webhook.get("timestamp")
    )

    erp_facts = {
        key: data.get(key)
        for key in ("id", "numero", "numeroLoja", "loja", "notaFiscal")
        if data.get(key) not in (None, "")
    }

    observations = _compact(
        _obs("order", situacao_id, updated_at, {"source": "situacao.id"}),
        _obs("erp", data.get("id"), updated_at, erp_facts),
    )
    return observations, DecisionContext()
