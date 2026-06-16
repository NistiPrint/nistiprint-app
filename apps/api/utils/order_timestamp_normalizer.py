from __future__ import annotations

import re
from datetime import UTC, date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


APP_TZ = ZoneInfo("America/Sao_Paulo")
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMERIC_RE = re.compile(r"^\d+$")
OFFSET_NO_COLON_RE = re.compile(r"([+-]\d{2})(\d{2})$")
OFFSET_HOUR_ONLY_RE = re.compile(r"([+-]\d{2})$")
BR_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")


def normalize_order_timestamp(value: Any) -> str | None:
    """Return an ISO timestamp with app offset, preserving unparseable non-empty values."""
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=APP_TZ)
    elif isinstance(value, (int, float)):
        dt = _datetime_from_epoch(value)
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        dt = _parse_datetime_string(value)
        if dt is None:
            return value
    else:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ).isoformat(timespec="seconds")


def build_order_timestamps(
    pedido: dict | None = None,
    snapshot: dict | None = None,
    shopee: dict | None = None,
    mercadolivre: dict | None = None,
) -> dict[str, str | None]:
    pedido = pedido or {}
    logistics = (snapshot or {}).get("logistics") or {}
    shopee = shopee or {}
    mercadolivre = mercadolivre or {}
    shopee_raw = shopee.get("raw_payload") or {}
    meli_raw = mercadolivre.get("raw_order") or {}

    return {
        "compra": _first_timestamp(
            pedido.get("data_compra_marketplace"),
            logistics.get("purchase_at"),
            logistics.get("compra_marketplace"),
            shopee.get("data_criacao"),
            shopee_raw.get("create_time"),
            mercadolivre.get("date_created"),
            meli_raw.get("date_created"),
            pedido.get("data_venda"),
        ),
        "pagamento": _first_timestamp(
            pedido.get("data_pagamento_marketplace"),
            logistics.get("payment_at"),
            logistics.get("pagamento_marketplace"),
            shopee.get("pay_time"),
            shopee.get("data_pagamento"),
            shopee_raw.get("pay_time"),
            mercadolivre.get("date_approved"),
            meli_raw.get("date_approved"),
        ),
        "coleta": _first_timestamp(
            pedido.get("data_coleta"),
            logistics.get("collection_at"),
            logistics.get("coleta"),
        ),
        "envio": _first_timestamp(
            pedido.get("data_envio_marketplace"),
            logistics.get("marketplace_shipped_at"),
            logistics.get("envio_marketplace"),
            shopee_raw.get("ship_time"),
            mercadolivre.get("date_closed"),
            meli_raw.get("date_closed"),
        ),
        "limite": _first_timestamp(
            pedido.get("data_limite_envio"),
            logistics.get("deadline"),
            logistics.get("ship_by_date"),
            logistics.get("expected_date"),
        ),
    }


def _first_timestamp(*values: Any) -> str | None:
    for value in values:
        normalized = normalize_order_timestamp(value)
        if normalized:
            return normalized
    return None


def _datetime_from_epoch(value: int | float | str) -> datetime:
    timestamp = float(value)
    if timestamp >= 10000000000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _parse_datetime_string(value: str) -> datetime | None:
    if NUMERIC_RE.match(value):
        return _datetime_from_epoch(value)

    br_match = BR_DATE_RE.match(value)
    if br_match:
        day, month, year, hour, minute, second = br_match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=APP_TZ,
        )

    normalized = value
    if DATE_ONLY_RE.match(normalized):
        normalized = f"{normalized}T00:00:00"
    normalized = normalized.replace(" ", "T", 1)
    normalized = OFFSET_NO_COLON_RE.sub(r"\1:\2", normalized)
    normalized = OFFSET_HOUR_ONLY_RE.sub(r"\1:00", normalized)
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
