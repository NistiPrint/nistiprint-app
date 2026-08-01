"""Canonical order-status lexicon.

Camada [A] do contrato em `docs/specs/03-contracts/canonizacao-status-pedido.md`.

Este modulo e o unico lugar do sistema que conhece vocabulario de provider.
Ele nao decide nada: apenas traduz `(provider, dominio, tipo, valor bruto)` em um
estagio canonico. A decisao de qual estagio vence esta em `order_status_decision`.

`integration_status_mappings` e a fonte autoritativa em runtime. O SEED abaixo e
a mesma matriz em forma de dado Python, usada para (1) gerar a migration de seed,
(2) servir de fallback auditavel quando o banco esta indisponivel e (3) alimentar
os testes sem exigir conexao.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Situacoes internas
# --------------------------------------------------------------------------- #

STATUS_PENDING = 1
STATUS_PAID = 2
STATUS_PRODUCED = 3
STATUS_READY_TO_SHIP = 4
STATUS_SHIPPED = 5
STATUS_DELIVERED = 6
STATUS_CANCELLED = 7
STATUS_RETURNED = 8

#: Situacoes que somente o modulo de producao pode atribuir. Ingest externo que
#: aponte para uma delas e rebaixado para `external_state_only`.
#:
#: 4 (Pronto para Envio) NAO esta aqui: na operacao real ela significa "o
#: marketplace emitiu a etiqueta/documentacao" e e alimentada exclusivamente por
#: ingest externo. 3 (Produzido) e o unico estado de producao interna.
INTERNAL_ONLY_SITUACOES = frozenset({STATUS_PRODUCED})


# --------------------------------------------------------------------------- #
# Estagios canonicos
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Stage:
    name: str
    rank: int
    situacao: int | None
    terminal: bool = False
    #: Quando `situacao is None`, distingue dois silencios muito diferentes:
    #:
    #: `fallback=True`  — o estagio e um *modificador* sobre o estado subjacente
    #:   ("ha uma devolucao a caminho deste pedido entregue"). A situacao correta
    #:   continua sendo a que as demais observacoes descrevem, entao a decisao
    #:   cai para o proximo estagio que projeta.
    #: `fallback=False` — o estagio e uma *duvida* sobre o destino do pedido
    #:   ("pediram cancelamento, ainda nao se sabe"). Nada deve ser projetado.
    fallback: bool = False


#: Vocabulario fechado. `rank` implementa a ordem de avaliacao da §7.1: entre
#: varias observacoes do mesmo pedido, vence a de maior rank.
STAGES: dict[str, Stage] = {
    stage.name: stage
    for stage in (
        Stage("returned", 100, STATUS_RETURNED, terminal=True),
        Stage("partially_refunded", 95, None, fallback=True),
        Stage("return_in_progress", 90, None, fallback=True),
        Stage("delivered", 80, STATUS_DELIVERED),
        Stage("shipped", 70, STATUS_SHIPPED),
        Stage("shipping_exception", 65, STATUS_SHIPPED),
        Stage("cancelled", 60, STATUS_CANCELLED),
        Stage("cancellation_pending", 55, None),
        Stage("fulfillment_ready", 45, STATUS_READY_TO_SHIP),
        Stage("paid_preparation", 40, STATUS_PAID),
        Stage("chargeback_pending", 30, None),
        Stage("payment_in_analysis", 20, STATUS_PENDING),
        Stage("awaiting_payment", 10, STATUS_PENDING),
        # Fato observado que deliberadamente nao descreve o pedido — por exemplo
        # uma etiqueta cancelada, que nao e cancelamento de venda.
        Stage("ignored", 1, None),
        Stage("unknown", 0, None),
    )
}

UNKNOWN_STAGE = STAGES["unknown"]

DOMAINS = (
    "order", "payment", "payment_detail", "shipping", "shipping_substatus",
    "return", "erp",
)

#: Dominios de *refinamento*: qualificam outro dominio em vez de descrever o
#: pedido sozinhos. A ausencia de mapeamento neles significa "sem informacao
#: adicional", nao "status desconhecido" — por isso nao contam como `unmapped`.
REFINEMENT_DOMAINS = frozenset({"shipping_substatus", "payment_detail"})


@dataclass(frozen=True)
class LexiconEntry:
    provider: str
    domain: str
    external_status_id: str
    stage: str
    #: O que o valor tambem afirma sobre outros dominios. Documental: alimenta as
    #: colunas de estado externo em `pedidos`, nunca a decisao.
    implies: tuple[str, ...] = ()
    source: str = "seed"

    @property
    def situacao(self) -> int | None:
        return STAGES[self.stage].situacao

    @property
    def rank(self) -> int:
        return STAGES[self.stage].rank


def _norm(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    return normalized or None


def _key(provider: Any, domain: Any, status: Any) -> tuple[str, str, str] | None:
    provider_n = (_norm(provider) or "").lower()
    domain_n = (_norm(domain) or "").lower()
    status_n = _norm(status)
    if not provider_n or not domain_n or not status_n:
        return None
    # Shopee usa MAIUSCULA, Meli minuscula, Bling numerico. A chave e case-insensitive.
    return provider_n, domain_n, status_n.upper()


# --------------------------------------------------------------------------- #
# SEED — matriz da §6
# --------------------------------------------------------------------------- #

def _entries(
    provider: str,
    domain: str,
    rows: dict[str, str | tuple[str, tuple[str, ...]]],
) -> dict[tuple[str, str, str], LexiconEntry]:
    built: dict[tuple[str, str, str], LexiconEntry] = {}
    for status, spec in rows.items():
        stage, implies = (spec, ()) if isinstance(spec, str) else spec
        if stage not in STAGES:
            raise ValueError(f"estagio desconhecido no seed: {stage}")
        key = _key(provider, domain, status)
        assert key is not None
        built[key] = LexiconEntry(provider, domain, status, stage, implies)
    return built


#: §6.1 — Shopee achata tudo em `order_status`. `implies` registra o que o valor
#: tambem afirma sobre pagamento e logistica, para os campos de estado externo.
_SHOPEE_ORDER = _entries("shopee", "order", {
    "UNPAID": ("awaiting_payment", ("payment:pending",)),
    "INVOICE_PENDING": ("paid_preparation", ("payment:paid",)),
    "READY_TO_SHIP": ("paid_preparation", ("payment:paid",)),
    "RETRY_SHIP": ("paid_preparation", ("payment:paid", "shipping:pickup_failed")),
    "PROCESSED": ("fulfillment_ready", ("payment:paid", "shipping:label_issued")),
    "SHIPPED": ("shipped", ("shipping:dispatched",)),
    "TO_CONFIRM_RECEIVE": ("shipped", ("shipping:in_transit",)),
    "COMPLETED": ("delivered", ("shipping:delivered",)),
    # Cancelamento na Shopee e solicitacao sujeita a recusa. Projetar 7 aqui
    # exigiria regredir de estado terminal quando a recusa chegasse.
    "IN_CANCEL": "cancellation_pending",
    "CANCELLED": "cancelled",
    "TO_RETURN": ("returned", ("return:open",)),
})

#: §6.2 — dominio proprio, alimentado por return_status / refund_status.
_SHOPEE_RETURN = _entries("shopee", "return", {
    "REQUESTED": "return_in_progress",
    "PROCESSING": "return_in_progress",
    "JUDGING": "return_in_progress",
    "SELLER_DISPUTE": "return_in_progress",
    "TO_RETURN": "return_in_progress",
    "RETURN": "return_in_progress",
    "RETURNING": "return_in_progress",
    "ACCEPTED": "returned",
    "APPROVED": "returned",
    "REFUND_PAID": "returned",
    "COMPLETED": "returned",
    "CLOSED": "returned",
    "RETURNED": "returned",
    "REFUNDED": "returned",
    "RETURN_COMPLETED": "returned",
    # Reembolso parcial nao encerra o pedido.
    "PARTIAL_REFUND": "partially_refunded",
    "PARTIALLY_REFUNDED": "partially_refunded",
    # Devolucao negada nao altera nada.
    "CANCELLED": "ignored",
    "SELLER_DISPUTE_SUCCESS": "ignored",
})

#: §6.3 — `rejected` e `cancelled` descrevem uma tentativa de pagamento, nunca o
#: pedido. Somente o dominio `order` cancela pedido.
_MELI_PAYMENT = _entries("mercadolivre", "payment", {
    "pending": "payment_in_analysis",
    "in_process": "payment_in_analysis",
    "authorized": "paid_preparation",
    "approved": "paid_preparation",
    "rejected": "awaiting_payment",
    "cancelled": "awaiting_payment",
    "canceled": "awaiting_payment",
    "in_mediation": "chargeback_pending",
    # Contestacao aberta nao e reversao: so a liquidacao decide.
    "charged_back": "chargeback_pending",
    # `refunded` total vira devolucao ou cancelamento conforme ja tenha havido
    # despacho — resolvido na projecao (§7.3), nao aqui.
    "refunded": "returned",
})

#: `status` + `status_detail` compostos pelo observer. O Meli so declara que o
#: dinheiro voltou de fato quando a contestacao esta liquidada.
_MELI_PAYMENT_DETAIL = _entries("mercadolivre", "payment_detail", {
    "charged_back:settled": "returned",
    "charged_back:reimbursed": "returned",
})

#: §6.4 — status de remessa.
_MELI_SHIPPING = _entries("mercadolivre", "shipping", {
    # `pending` significa que o registro de envio existe e nada foi decidido.
    # Nao e evidencia de pagamento: um pedido aguardando pagamento tambem tem
    # shipment pendente.
    "pending": "ignored",
    "handling": "paid_preparation",
    "to_be_shipped": "paid_preparation",
    # `ready_to_ship` do Meli e "aguardando envio", nao "etiqueta emitida" — a
    # etiqueta pode nem ter sido impressa. Nao equivale ao PROCESSED da Shopee.
    "ready_to_ship": "paid_preparation",
    "shipped": "shipped",
    "delivered": "delivered",
    "not_delivered": "shipping_exception",
    # Etiqueta cancelada nao e venda cancelada: o vendedor pode emitir outra.
    "cancelled": "ignored",
    "canceled": "ignored",
})

#: Substatus e observacao independente do status (§8): entra como uma segunda
#: observacao no mesmo dominio e disputa por rank. Assim `delivered` + substatus
#: `in_transit` continua entregue, e `returned_to_warehouse` vence qualquer coisa.
_MELI_SHIPPING_SUBSTATUS = _entries("mercadolivre", "shipping_substatus", {
    "authorized_by_carrier": "shipped",
    "dropped_off": "shipped",
    "in_hub": "shipped",
    "in_transit": "shipped",
    "picked_up": "shipped",
    "picked_up_for_return": "return_in_progress",
    "returned_to_agency": "return_in_progress",
    "returned_to_hub": "return_in_progress",
    "returning_to_hub": "return_in_progress",
    "returning_to_sender": "return_in_progress",
    "returning_to_warehouse": "return_in_progress",
    "soon_to_be_returned": "return_in_progress",
    "returned": "returned",
    "returned_to_warehouse": "returned",
})

#: §6.5 — estado agregado do pedido.
_MELI_ORDER = _entries("mercadolivre", "order", {
    "confirmed": "awaiting_payment",
    "opened": "awaiting_payment",
    "payment_required": "awaiting_payment",
    "payment_in_process": "awaiting_payment",
    "partially_paid": "awaiting_payment",
    "paid": "paid_preparation",
    "partially_refunded": "partially_refunded",
    "pending_cancel": "cancellation_pending",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "invalid": "cancelled",
})

#: §6.6 — devolucao como entidade propria.
_MELI_RETURN = _entries("mercadolivre", "return", {
    "delivered": "returned",
    "label_generated": "return_in_progress",
    "pending": "return_in_progress",
    "pending_delivered": "return_in_progress",
    "pending_expiration": "return_in_progress",
    "pending_failure": "return_in_progress",
    "scheduled": "return_in_progress",
    "shipped": "return_in_progress",
    "closed": "returned",
    # `status_money` do retorno, emitido como observacao propria pelo observer.
    "refunded": "returned",
    "cancelled": "ignored",
})

#: §6.7 — Bling. `9` (Atendido) e baixa no ERP, nao confirmacao de entrega da
#: transportadora: projeta 5, nunca 6.
_BLING_ORDER = _entries("bling", "order", {
    "6": "awaiting_payment",
    "15": "paid_preparation",
    "24": "fulfillment_ready",
    "9": "shipped",
    "12": "cancelled",
    # Arquivamento e organizacao interna do ERP, nao ciclo de vida.
    "18": "ignored",
})


SEED_LEXICON: dict[tuple[str, str, str], LexiconEntry] = {
    **_SHOPEE_ORDER,
    **_SHOPEE_RETURN,
    **_MELI_ORDER,
    **_MELI_PAYMENT,
    **_MELI_PAYMENT_DETAIL,
    **_MELI_SHIPPING,
    **_MELI_SHIPPING_SUBSTATUS,
    **_MELI_RETURN,
    **_BLING_ORDER,
}


# --------------------------------------------------------------------------- #
# Resolver
# --------------------------------------------------------------------------- #


class LexiconResolver:
    """Traduz status externo em estagio canonico.

    Consulta `integration_status_mappings` (autoritativa) com cache de processo e
    cai para o SEED apenas quando o banco falha. Uma ausencia real no banco *nao*
    cai para o seed silenciosamente: se a linha existe no banco com outro estagio,
    o banco vence; se nao existe em lugar nenhum, o resultado e `unmapped`.
    """

    def __init__(self, *, ttl_seconds: float = 300.0, seed: dict | None = None) -> None:
        self._ttl = ttl_seconds
        self._seed = SEED_LEXICON if seed is None else seed
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str, str], LexiconEntry] | None = None
        self._cache_loaded_at = 0.0
        self._db_available = True

    # -- API ---------------------------------------------------------------- #

    def lookup(
        self,
        provider: Any,
        domain: Any,
        external_status_id: Any,
        *,
        integration_id: int | None = None,
    ) -> LexiconEntry | None:
        key = _key(provider, domain, external_status_id)
        if key is None:
            return None

        overrides = self._overrides()
        if integration_id is not None:
            scoped = overrides.get((*key, str(integration_id)))  # type: ignore[arg-type]
            if scoped is not None:
                return scoped
        entry = overrides.get(key)
        if entry is not None:
            return entry
        return self._seed.get(key)

    def stage(self, *args: Any, **kwargs: Any) -> Stage:
        entry = self.lookup(*args, **kwargs)
        return STAGES[entry.stage] if entry else UNKNOWN_STAGE

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._cache_loaded_at = 0.0

    # -- interno ------------------------------------------------------------ #

    def _overrides(self) -> dict:
        now = time.monotonic()
        with self._lock:
            fresh = (
                self._cache is not None
                and (now - self._cache_loaded_at) < self._ttl
            )
            if fresh:
                return self._cache  # type: ignore[return-value]
        loaded = self._load_overrides()
        with self._lock:
            self._cache = loaded
            self._cache_loaded_at = now
        return loaded

    def _load_overrides(self) -> dict:
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db

            rows = (
                supabase_db.table("integration_status_mappings")
                .select(
                    "module_id,integration_id,status_domain,external_status_id,"
                    "lifecycle_stage"
                )
                .eq("is_active", True)
                .not_.is_("lifecycle_stage", "null")
                .execute()
                .data
                or []
            )
        except Exception as exc:  # pragma: no cover - degradacao auditavel
            if self._db_available:
                logger.warning(
                    "[status-lexicon] banco indisponivel, usando seed local: %s", exc
                )
                self._db_available = False
            return {}

        self._db_available = True
        overrides: dict = {}
        for row in rows if isinstance(rows, list) else []:
            stage = _norm(row.get("lifecycle_stage"))
            if stage not in STAGES:
                logger.warning(
                    "[status-lexicon] estagio invalido no banco module=%s status=%s stage=%s",
                    row.get("module_id"),
                    row.get("external_status_id"),
                    stage,
                )
                continue
            key = _key(
                row.get("module_id"),
                row.get("status_domain"),
                row.get("external_status_id"),
            )
            if key is None:
                continue
            entry = LexiconEntry(
                key[0], key[1], str(row.get("external_status_id")), str(stage),
                source="db",
            )
            integration_id = row.get("integration_id")
            if integration_id in (None, ""):
                overrides[key] = entry
            else:
                overrides[(*key, str(integration_id))] = entry
        return overrides


lexicon = LexiconResolver()
