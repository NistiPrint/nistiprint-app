"""Canonical order-status decision and projection.

Camada [B] e [C] do contrato em
`docs/specs/03-contracts/canonizacao-status-pedido.md`.

Este modulo nao conhece provider algum. Recebe observacoes de dominio ja
normalizadas pelos drivers, resolve qual estagio canonico descreve o pedido
(§7.1) e projeta a situacao interna sobre a anterior com as guardas de
terminalidade e nao-regressao (§7.6).

Se aparecer aqui um `if provider == ...`, a regra esta no lugar errado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

from nistiprint_shared.services.order_status_lexicon import (
    INTERNAL_ONLY_SITUACOES,
    REFINEMENT_DOMAINS,
    STAGES,
    STATUS_CANCELLED,
    STATUS_DELIVERED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_PRODUCED,
    STATUS_READY_TO_SHIP,
    STATUS_RETURNED,
    STATUS_SHIPPED,
    LexiconEntry,
    LexiconResolver,
    lexicon as default_lexicon,
)

Domain = Literal["order", "payment", "shipping", "shipping_substatus", "return", "erp"]


# --------------------------------------------------------------------------- #
# Observacao de dominio — o unico output de um driver
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DomainObservation:
    """Fato bruto observado num dominio, sem traducao.

    O driver preenche `external_status_id` com o valor exatamente como o provider
    o entregou. Traduzir e trabalho do lexico.
    """

    domain: Domain
    external_status_id: str | None
    provider_occurred_at: str | None = None
    provider_sequence: int | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionContext:
    """Fatos que nao sao status mas condicionam a decisao."""

    #: Momento do despacho, quando o provider o expoe. Distingue reembolso total
    #: antes do envio (cancelamento) de depois do envio (devolucao) — §7.3.
    shipped_at: str | None = None
    #: Reembolso explicitamente parcial. Impede que uma devolucao parcial feche
    #: o pedido.
    partial_refund: bool = False


@dataclass(frozen=True)
class CanonicalDecision:
    lifecycle_stage: str
    target_situacao_pedido_id: int | None
    reason: str
    order_status: str | None = None
    payment_status: str | None = None
    shipping_status: str | None = None
    shipping_substatus: str | None = None
    return_status: str | None = None
    observed_at: str | None = None
    unmapped: tuple[str, ...] = ()

    @property
    def is_unmapped(self) -> bool:
        return self.lifecycle_stage == "unknown" and bool(self.unmapped)


# --------------------------------------------------------------------------- #
# §7.2 — pagamento efetivo entre varias tentativas
# --------------------------------------------------------------------------- #

#: Uma tentativa recusada ao lado de uma aprovada nunca degrada o pedido.
PAYMENT_PRECEDENCE = (
    "approved",
    "authorized",
    "in_process",
    "pending",
    "refunded",
    "charged_back",
    "in_mediation",
    "cancelled",
    "canceled",
    "rejected",
)


def effective_payment_status(payments: Iterable[Any]) -> str | None:
    statuses: list[str] = []
    for row in payments or ():
        value = row.get("status") if isinstance(row, dict) else row
        normalized = _lower(value)
        if normalized:
            statuses.append(normalized)
    if not statuses:
        return None
    for candidate in PAYMENT_PRECEDENCE:
        if candidate in statuses:
            return candidate
    return statuses[0]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_DISPATCH_STAGES = {"shipped", "shipping_exception", "delivered"}


def _lower(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    return str(value).strip()


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def latest_timestamp(*values: Any) -> str | None:
    best: tuple[datetime, str] | None = None
    for value in values:
        normalized = _timestamp(value)
        if not normalized:
            continue
        parsed = _parse(normalized)
        if parsed is None:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, normalized)
    return best[1] if best else None


# --------------------------------------------------------------------------- #
# §7.1 — decisao
# --------------------------------------------------------------------------- #


def decide(
    provider: str,
    observations: Iterable[DomainObservation],
    *,
    context: DecisionContext | None = None,
    resolver: LexiconResolver | None = None,
    integration_id: int | None = None,
) -> CanonicalDecision:
    """Resolve o estagio canonico a partir das observacoes de um pedido."""
    resolver = resolver or default_lexicon
    context = context or DecisionContext()
    observations = [obs for obs in observations if obs.external_status_id]

    by_domain: dict[str, str] = {}
    unmapped: list[str] = []
    ranked: list[tuple[int, str, DomainObservation]] = []

    for obs in observations:
        if obs.domain == "erp":
            # Dominio fiscal/identidade: nunca descreve ciclo de vida.
            continue
        by_domain.setdefault(obs.domain, str(obs.external_status_id))
        entry = resolver.lookup(
            provider, obs.domain, obs.external_status_id, integration_id=integration_id
        )
        if entry is None:
            if obs.domain not in REFINEMENT_DOMAINS:
                unmapped.append(f"{obs.domain}:{obs.external_status_id}")
            continue
        ranked.append((entry.rank, entry.stage, obs))

    ranked.sort(key=lambda item: item[0], reverse=True)
    winner = ranked[0] if ranked else None

    observed_at = latest_timestamp(
        *(obs.provider_occurred_at for obs in observations)
    )

    common = {
        "order_status": by_domain.get("order"),
        "payment_status": by_domain.get("payment"),
        "shipping_status": by_domain.get("shipping"),
        "shipping_substatus": by_domain.get("shipping_substatus"),
        "return_status": by_domain.get("return"),
        # `payment_detail` nao aparece no contrato publico: e refinamento.
        "observed_at": observed_at,
        "unmapped": tuple(unmapped),
    }

    if winner is None:
        return CanonicalDecision(
            "unknown", None,
            "unmapped_provider_state" if unmapped else "no_observation",
            **common,
        )

    _, original_stage, source_obs = winner
    stage_name = original_stage
    reason = f"{source_obs.domain}:{source_obs.external_status_id}"

    stage_name, reason = _apply_refund_rules(
        stage_name, reason, source_obs, observations, context, provider, resolver,
        integration_id,
    )

    stage = STAGES[stage_name]
    situacao = stage.situacao
    if situacao is None and stage.fallback:
        # Estagio modificador: a situacao continua sendo a que o restante das
        # observacoes descreve (§7.1).
        situacao, underlying = _underlying_situacao(
            ranked, skip={original_stage, stage_name}
        )
        if underlying:
            reason = f"{reason}:over_{underlying}"

    return CanonicalDecision(stage.name, situacao, reason, **common)


def _underlying_situacao(
    ranked: list[tuple[int, str, DomainObservation]],
    *,
    skip: set[str],
) -> tuple[int | None, str | None]:
    """Maior estagio que de fato projeta, ignorando o modificador que venceu.

    `skip` traz tanto o estagio bruto do vencedor quanto o estagio para o qual
    ele foi reescrito: uma devolucao parcial nao pode cair de volta na propria
    observacao de devolucao que a originou.
    """
    for _rank, stage_name, _obs in ranked:
        if stage_name in skip:
            continue
        candidate = STAGES[stage_name]
        if candidate.situacao is not None:
            return candidate.situacao, stage_name
    return None, None


def _apply_refund_rules(
    stage_name: str,
    reason: str,
    source_obs: DomainObservation,
    observations: list[DomainObservation],
    context: DecisionContext,
    provider: str,
    resolver: LexiconResolver,
    integration_id: int | None,
) -> tuple[str, str]:
    """§7.3 — reembolso total antes do despacho e cancelamento, nao devolucao."""
    if stage_name != "returned":
        return stage_name, reason

    if context.partial_refund:
        return "partially_refunded", f"{reason}:partial_refund_does_not_close_order"

    if source_obs.domain not in {"payment", "payment_detail"}:
        return stage_name, reason

    if _has_dispatch_evidence(observations, context, provider, resolver, integration_id):
        return stage_name, f"{reason}:full_payment_reversal_after_shipping"
    return "cancelled", f"{reason}:full_payment_reversal_before_shipping"


def _has_dispatch_evidence(
    observations: list[DomainObservation],
    context: DecisionContext,
    provider: str,
    resolver: LexiconResolver,
    integration_id: int | None,
) -> bool:
    if context.shipped_at:
        return True
    for obs in observations:
        if obs.domain not in {"shipping", "shipping_substatus"}:
            continue
        entry = resolver.lookup(
            provider, obs.domain, obs.external_status_id, integration_id=integration_id
        )
        if entry is not None and entry.stage in _DISPATCH_STAGES:
            return True
    return False


# --------------------------------------------------------------------------- #
# §7.4 — autoridade por origem
# --------------------------------------------------------------------------- #

#: Quem pode projetar situacao em cada `ingest_origin_mode`. O dominio `erp`
#: fica sempre fora: e identidade e fiscal, nunca ciclo de vida.
_LIFECYCLE_AUTHORITY = {
    "marketplace_direct": {"marketplace"},
    "erp_bling": {"erp"},
    "erp_only_dummy": {"erp"},
}

#: Origens que nunca alteram estado, em nenhum modo.
_NEVER_AUTHORITATIVE = {"chat"}


def is_authoritative(ingest_origin_mode: Any, source_kind: Any, domain: Any) -> bool:
    """A observacao pode projetar situacao neste vinculo?

    `source_kind` e "marketplace", "erp" ou "chat". Uma observacao nao
    autoritativa continua sendo persistida como fato externo e transicao
    auditavel — e o que permite reconciliar divergencia Bling x marketplace sem
    disputa de escrita.
    """
    kind = _lower(source_kind)
    if kind in _NEVER_AUTHORITATIVE:
        return False
    if _lower(domain) == "erp":
        return False
    allowed = _LIFECYCLE_AUTHORITY.get(_lower(ingest_origin_mode) or "", set())
    return kind in allowed


# --------------------------------------------------------------------------- #
# §7.6 — projecao
# --------------------------------------------------------------------------- #


def project_operational_status(previous: int | None, target: int | None) -> int | None:
    """Aplica o alvo sobre a situacao anterior. Espelha o RPC do banco.

    Regras, nesta ordem:
      - 8 absorve tudo e nunca sai;
      - 3 e 4 sao internos: ingest externo nunca os atinge;
      - 6 e 7 so cedem para 8;
      - cancelamento depois do despacho preserva 5/6 (so devolucao move para 8);
      - nenhuma projecao regride no eixo pago -> enviado -> entregue.
    """
    if target is None:
        return previous
    if target == STATUS_RETURNED or previous == STATUS_RETURNED:
        return STATUS_RETURNED
    if target in INTERNAL_ONLY_SITUACOES:
        # 3 (Produzido) e do modulo de producao. Chegar aqui vindo de ingest
        # externo significa lexico mal configurado; preserva o estado interno.
        return previous
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
    if target == STATUS_READY_TO_SHIP:
        # Producao interna (3) nao regride para "pronto para envio" so porque o
        # marketplace emitiu a etiqueta: os dois eixos sao concorrentes.
        if previous == STATUS_PRODUCED:
            return STATUS_PRODUCED
        return (
            STATUS_READY_TO_SHIP
            if previous in (None, STATUS_PENDING, STATUS_PAID, STATUS_READY_TO_SHIP)
            else previous
        )
    if target == STATUS_PAID:
        return STATUS_PAID if previous in (None, STATUS_PENDING, STATUS_PAID) else previous
    if target == STATUS_PENDING:
        return STATUS_PENDING if previous in (None, STATUS_PENDING) else previous
    return previous
