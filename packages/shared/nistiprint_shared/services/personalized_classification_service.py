"""
Shared personalized item classification helpers.

This module owns the lightweight ingest rule: classify by item description/name
already present in the order payload, without extra API calls.
"""

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonalizedItemMatch:
    index: int
    item: dict
    descricao: str | None
    bling_item_id: Any = None


@dataclass(frozen=True)
class PersonalizedClassification:
    is_personalized: bool
    matched_items: list[PersonalizedItemMatch]


def normalize_personalization_text(value: Any) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def item_text_candidates(item: dict | None) -> list[Any]:
    if not isinstance(item, dict):
        return []

    produto = item.get("produto") if isinstance(item.get("produto"), dict) else {}
    return [
        item.get("descricao"),
        item.get("nome"),
        item.get("name"),
        produto.get("nome"),
        produto.get("descricao"),
        produto.get("name"),
    ]


def item_indicates_personalized(item: dict | None) -> bool:
    searchable = " ".join(str(value) for value in item_text_candidates(item) if value)
    return "personaliz" in normalize_personalization_text(searchable)


def classify_items(items: Iterable[dict] | None) -> PersonalizedClassification:
    matched = []
    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        if item_indicates_personalized(item):
            matched.append(
                PersonalizedItemMatch(
                    index=idx,
                    item=item,
                    descricao=item.get("descricao") or item.get("name") or item.get("nome"),
                    bling_item_id=item.get("id") or item.get("bling_item_id"),
                )
            )
    return PersonalizedClassification(
        is_personalized=bool(matched),
        matched_items=matched,
    )


def classify_order_payload(payload: dict | None) -> PersonalizedClassification:
    if not isinstance(payload, dict):
        return PersonalizedClassification(is_personalized=False, matched_items=[])
    return classify_items(payload.get("itens") or payload.get("items") or [])


def persist_classification_from_payload(
    payload: dict,
    pedido_id: int | None,
    *,
    db=supabase_db,
    log: logging.Logger | None = None,
) -> PersonalizedClassification:
    """
    Persist canonical/legacy personalized flags using the shared lightweight rule.
    """
    active_logger = log or logger
    classification = classify_order_payload(payload)

    if not pedido_id:
        active_logger.warning(
            "[personalized-classification] sem pedido_id para pedido=%s",
            (payload or {}).get("numeroLoja") or (payload or {}).get("numero"),
        )
        return classification

    try:
        db.table("pedidos").update({
            "personalizado": classification.is_personalized,
            "updated_at": get_now_iso(),
        }).eq("id", pedido_id).execute()

        pedido_res = (
            db.table("pedidos")
            .select("pedido_bling_id")
            .eq("id", pedido_id)
            .maybe_single()
            .execute()
        )
        pedido_row = getattr(pedido_res, "data", None) or {}
        pedido_bling_id = pedido_row.get("pedido_bling_id")
        if pedido_bling_id:
            db.table("pedidos_bling").update({
                "personalizado": classification.is_personalized,
                "updated_at": get_now_iso(),
            }).eq("id", pedido_bling_id).execute()

        for match in classification.matched_items:
            if match.descricao:
                db.table("itens_pedido").update({
                    "personalizado": True,
                    "updated_at": get_now_iso(),
                }).eq("pedido_id", pedido_id).eq("descricao", match.descricao).execute()

            if match.bling_item_id:
                db.table("itens_pedido_bling").update({
                    "personalizado": True,
                    "updated_at": get_now_iso(),
                }).eq("bling_item_id", str(match.bling_item_id)).execute()

        active_logger.info(
            "[personalized-classification] pedido=%s personalizado=%s itens=%d",
            pedido_id,
            classification.is_personalized,
            len(classification.matched_items),
        )
    except Exception as exc:
        active_logger.warning(
            "[personalized-classification] falha ao persistir pedido_id=%s: %s",
            pedido_id,
            exc,
        )

    return classification

