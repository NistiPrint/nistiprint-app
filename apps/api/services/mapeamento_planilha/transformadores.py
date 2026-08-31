from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


def limpar_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return None
    if re.fullmatch(r"[-+]?\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def inteiro(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def moeda_br(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        text = str(value).strip().replace("R$", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", ".")
        return float(Decimal(text))
    except (InvalidOperation, TypeError, ValueError):
        return None


def data_tz_sp(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    parsed = pd.to_datetime(value, errors="coerce", dayfirst="/" in text)
    if pd.isna(parsed):
        return None
    if isinstance(parsed, datetime):
        return parsed.isoformat()
    return parsed.to_pydatetime().isoformat()


def constante(value: Any) -> int:
    return 1


def situacao_shopee(value: Any) -> int | None:
    return _status(value)


def situacao_mercadolivre(value: Any) -> int | None:
    return _status(value)


def forma_entrega_para_canonica(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if "flex" in text:
        return "FLEX"
    if "fulfillment" in text or "full" in text:
        return "FULFILLMENT"
    if "express" in text or "expresso" in text:
        return "EXPRESS"
    return "STANDARD"


def _status(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return {
        "pendente": 1,
        "pago": 2,
        "em andamento": 2,
        "em producao": 3,
        "processando": 3,
        "pronto para envio": 4,
        "enviado": 5,
        "entregue": 6,
        "cancelado": 7,
        "devolvido": 8,
    }.get(text)
