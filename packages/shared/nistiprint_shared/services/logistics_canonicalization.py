"""Canonizacao logistica: prazo de postagem, modalidade e identidade do comprador.

Mesma arquitetura da canonizacao de status (`order_status_decision.py`): o driver
observa o payload do provider e devolve fatos crus; a decisao canonica nao
conhece provider algum.

    Se aparecer um `if provider == ...` fora da secao de drivers, a regra esta no
    lugar errado.

## O que se canoniza

`data_limite_envio` — **prazo de postagem**, nao de entrega. E o momento ate o
qual a mercadoria precisa sair daqui. E o unico prazo que a producao consegue
usar: prazo de entrega inclui transporte, que nao controlamos.

Cada marketplace expoe isso com nome proprio:

| Provider | Campo | Observado em producao (02/08/2026) |
|---|---|---|
| Shopee | `ship_by_date` | 1.314 de 1.397 snapshots (94%), ja em ISO |
| Mercado Livre | `sla.expected_date` (de `/shipments/{id}/sla`) | 280 de 317 (88%) |

O ML tem endpoint dedicado para isso — `/shipments/{id}/sla` — e o driver ja o
consulta (`meli_driver.get_shipment_sla`). O valor vem no formato do prazo de
postagem. `buffering.date` representa outra informacao logistica e nunca
substitui o prazo oficial de despacho.

**Atencao ao formato:** o SLA aparece como objeto no ingest direto e como lista
em `bling_order_processing_service`. Os dois existem em producao.

**Quando o provider nao informa nada, nao se inventa.** Derivar de
`date_created + handling` no ML daria numero para 100% dos casos, mas `handling`
vem zerado la e o resultado seria um prazo igual ao momento da compra — pior que
ausencia, porque parece um dado.

**Shopee: `days_to_ship` nao substitui o prazo oficial.** A soma de dias ao
pagamento diverge do painel, sobretudo enquanto `ship_by_date` vem zerado.
Um prazo ausente permanece ausente e volta pela reconciliacao; a torre o soma
na data da proxima coleta disponivel. Uma consulta
incompleta preserva o ultimo prazo confirmado. Datas conferidas no painel
podem ser registradas com origem explicita, sem falsificar `ship_by_date`.

## Modalidade

Vocabulario canonico ja em uso no banco: `STANDARD`, `FLEX`, `FULFILLMENT`,
mais `RETIRADA` para retirada pelo comprador. `EXPRESS` aparece em
`regras_logisticas_integracao` como sinonimo historico de `FLEX` e e tratado
como alias por `logistica_coleta_service`.

Distribuicao real que sustenta o mapeamento:

    Shopee    Shopee Xpress / fulfilled_by_local_seller   1024  -> STANDARD
              Full / fulfilled_by_shopee                   239  -> FULFILLMENT
              Entrega Rapida / fulfilled_by_local_seller   123  -> FLEX
              Retirada pelo Comprador                       11  -> RETIRADA

    ML        me2 / xd_drop_off                             95  -> STANDARD
              me2 / fulfillment                             20  -> FULFILLMENT
              me2 / self_service                             4  -> FLEX

O ingest lia `shipment.logistic_type` e `shipping_option.name` para o ML; o
payload real traz `shipment.logistic.type`. Por isso nenhum pedido ML jamais foi
classificado como FLEX.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Modalidade = Literal["STANDARD", "FLEX", "FULFILLMENT", "RETIRADA"]

STANDARD: Modalidade = "STANDARD"
FLEX: Modalidade = "FLEX"
FULFILLMENT: Modalidade = "FULFILLMENT"
RETIRADA: Modalidade = "RETIRADA"

#: `EXPRESS` sobrevive em regras cadastradas; significa o mesmo que FLEX.
MODALIDADE_ALIASES = {"EXPRESS": FLEX}


# --------------------------------------------------------------------------- #
# Observacao — o unico output de um driver
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LogisticsObservation:
    """Fatos crus observados no payload, sem traducao."""

    provider: str
    #: Prazo de postagem exatamente como o provider entregou.
    dispatch_deadline_raw: Any = None
    #: Campo de onde o prazo veio — entra na auditoria.
    dispatch_deadline_field: str | None = None
    #: Sinais de modalidade, em ordem de precedencia.
    carrier: str | None = None
    logistic_type: str | None = None
    logistic_mode: str | None = None
    fulfillment_flag: str | None = None
    #: Identidade do comprador. Hoje so a Shopee expoe username estavel.
    buyer_username: str | None = None
    buyer_user_id: Any = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalLogistics:
    """Resultado pronto para persistir em `pedidos`."""

    data_limite_envio: str | None
    modalidade_logistica: Modalidade
    is_flex: bool
    is_fulfillment: bool
    buyer_username: str | None
    buyer_user_id: int | None
    #: Explica a decisao. Vai para o snapshot e para o log de ingest.
    reason: str
    dispatch_deadline_source: str | None = None

    def to_order_fields(self) -> dict:
        """Campos a aplicar no upsert do pedido, sem os nulos."""
        campos = {
            "data_limite_envio": self.data_limite_envio,
            "modalidade_logistica": self.modalidade_logistica,
            "is_flex": self.is_flex,
            "is_fulfillment": self.is_fulfillment,
            "buyer_username": self.buyer_username,
            "buyer_user_id": self.buyer_user_id,
        }
        return {k: v for k, v in campos.items() if v is not None}


# --------------------------------------------------------------------------- #
# Normalizacao
# --------------------------------------------------------------------------- #


def _normalize_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    texto = str(value)
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def normalize_deadline(value: Any) -> str | None:
    """Converte o prazo para ISO 8601, aceitando epoch, ISO ou datetime.

    A Shopee entrega epoch em alguns endpoints e ISO em outros; o ML entrega ISO
    com sufixo `Z` ou offset. Aceitar as tres formas evita que a canonizacao
    dependa de qual endpoint respondeu.
    """
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    texto = str(value).strip()
    if not texto:
        return None
    if texto.isdigit():
        try:
            return datetime.fromtimestamp(int(texto), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def canonical_modalidade(value: Any) -> Modalidade | None:
    texto = str(value or "").strip().upper()
    if not texto:
        return None
    texto = MODALIDADE_ALIASES.get(texto, texto)
    return texto if texto in (STANDARD, FLEX, FULFILLMENT, RETIRADA) else None


# --------------------------------------------------------------------------- #
# Drivers — a unica parte que conhece provider
# --------------------------------------------------------------------------- #


def observe_shopee(detail: dict | None) -> LogisticsObservation:
    detail = detail or {}
    raw = detail.get("raw") or {}

    prazo = normalize_deadline(detail.get("ship_by_date")) or normalize_deadline(raw.get("ship_by_date"))
    campo = "shopee.ship_by_date" if prazo else None

    return LogisticsObservation(
        provider="shopee",
        dispatch_deadline_raw=prazo,
        dispatch_deadline_field=campo,
        carrier=detail.get("shipping_carrier"),
        fulfillment_flag=detail.get("fulfillment_flag") or raw.get("fulfillment_flag"),
        buyer_username=detail.get("buyer_username") or raw.get("buyer_username"),
        buyer_user_id=detail.get("buyer_user_id") or raw.get("buyer_user_id"),
        raw=detail,
    )


def _meli_sla(detail: dict) -> dict:
    """Normaliza o SLA, que aparece como objeto ou como lista.

    O ingest direto guarda objeto; `bling_order_processing_service` trata como
    lista e le `[0]`. Os dois formatos existem em producao, entao aceitar so um
    deles deixaria metade dos pedidos sem prazo.
    """
    sla = detail.get("sla")
    if isinstance(sla, list):
        sla = sla[0] if sla else None
    return sla if isinstance(sla, dict) else {}


def observe_mercadolivre(detail: dict | None) -> LogisticsObservation:
    detail = detail or {}
    shipment = detail.get("shipment") or {}
    lead_time = shipment.get("lead_time") or {}
    logistic = shipment.get("logistic") or {}

    # `/shipments/{id}/sla` e a fonte autoritativa do prazo de POSTAGEM do ML —
    # o endpoint existe para exatamente isso, e o driver ja o consulta. Medido em
    # producao: `sla.expected_date` cobre 280 de 317 snapshots (88%), contra 60
    # (19%) de `lead_time.buffering.date`. O formato tambem e o esperado
    # (23:59:59 no fuso local), enquanto `buffering` traz o corte de coleta.
    #
    # SLA ausente nao inventa prazo; consultas incompletas preservam o fato salvo.
    # `estimated_delivery_*` nunca entra: e prazo de ENTREGA, que inclui
    # transporte e nao serve para decidir producao.
    sla = _meli_sla(detail)
    prazo = sla.get("expected_date")
    campo = "mercadolivre.sla.expected_date"
    # Buffering libera a etiqueta; nao informa o prazo oficial de despacho.

    # Compatibilidade com o formato antigo (`logistic_type` na raiz), que ainda
    # aparece em payloads de webhook mais enxutos.
    logistic_type = logistic.get("type") or shipment.get("logistic_type")
    logistic_mode = logistic.get("mode") or shipment.get("mode")

    return LogisticsObservation(
        provider="mercadolivre",
        dispatch_deadline_raw=prazo,
        dispatch_deadline_field=campo,
        carrier=(lead_time.get("shipping_method") or {}).get("name") or shipment.get("mode"),
        logistic_type=logistic_type,
        logistic_mode=logistic_mode,
        raw=detail,
    )


OBSERVERS = {
    "shopee": observe_shopee,
    "mercadolivre": observe_mercadolivre,
}


def observe(provider: str, detail: dict | None) -> LogisticsObservation | None:
    observer = OBSERVERS.get(str(provider or "").strip().lower())
    return observer(detail) if observer else None


# --------------------------------------------------------------------------- #
# Decisao canonica — provider-agnostica
# --------------------------------------------------------------------------- #

#: Sinais textuais de modalidade, avaliados por precedencia. Ficam aqui, e nao
#: no driver, porque a mesma palavra significa a mesma coisa em toda plataforma.
_SINAIS = (
    (FULFILLMENT, ("fulfillment", "fulfilled_by_shopee", "full")),
    (RETIRADA, ("retirada pelo comprador", "buyer_pickup", "pickup")),
    (FLEX, ("self_service", "entrega rapida", "flex", "prioritario")),
)


def _classificar(*valores: Any) -> tuple[Modalidade, str] | None:
    normalizados = [(_normalize_text(v), v) for v in valores if v not in (None, "")]
    for modalidade, marcadores in _SINAIS:
        for normalizado, original in normalizados:
            for marcador in marcadores:
                # Igualdade para marcadores curtos evita que "full" case dentro
                # de "fulfilled_by_local_seller", que e o oposto do que indica.
                casou = (
                    normalizado == marcador
                    if len(marcador) <= 4
                    else marcador in normalizado
                )
                if casou:
                    return modalidade, f"{original!r} indica {modalidade}"
    return None


def decide(observation: LogisticsObservation | None) -> CanonicalLogistics:
    if observation is None:
        return CanonicalLogistics(
            data_limite_envio=None,
            modalidade_logistica=STANDARD,
            is_flex=False,
            is_fulfillment=False,
            buyer_username=None,
            buyer_user_id=None,
            reason="sem observacao logistica; assumindo STANDARD",
        )

    deadline = normalize_deadline(observation.dispatch_deadline_raw)

    classificacao = _classificar(
        observation.fulfillment_flag,
        observation.logistic_type,
        observation.carrier,
        observation.logistic_mode,
    )
    if classificacao:
        modalidade, motivo = classificacao
    else:
        modalidade, motivo = STANDARD, "nenhum sinal reconhecido; STANDARD por omissao"

    if deadline is None:
        motivo += "; prazo nao informado pelo provider"

    buyer_user_id = None
    if observation.buyer_user_id not in (None, ""):
        try:
            buyer_user_id = int(observation.buyer_user_id)
        except (TypeError, ValueError):
            buyer_user_id = None

    username = (observation.buyer_username or "").strip() or None

    return CanonicalLogistics(
        data_limite_envio=deadline,
        modalidade_logistica=modalidade,
        is_flex=modalidade == FLEX,
        is_fulfillment=modalidade == FULFILLMENT,
        buyer_username=username,
        buyer_user_id=buyer_user_id,
        reason=motivo,
        dispatch_deadline_source=observation.dispatch_deadline_field if deadline else None,
    )


def resolve(provider: str, detail: dict | None) -> CanonicalLogistics:
    """Atalho: observa e decide."""
    return decide(observe(provider, detail))
