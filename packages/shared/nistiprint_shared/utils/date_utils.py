from datetime import datetime, timezone
from typing import Any

import pytz

from nistiprint_shared.constants import APP_TIMEZONE

APP_TZ = pytz.timezone(APP_TIMEZONE)
UTC = timezone.utc


def get_now():
    """Retorna o datetime atual no fuso horario da aplicacao."""
    return datetime.now(APP_TZ)


def get_utc_now():
    """Retorna o datetime atual em UTC com timezone."""
    return datetime.now(UTC)


def get_now_iso():
    """Retorna o datetime atual em ISO com o fuso horario da aplicacao."""
    return get_now().isoformat()


def get_utc_now_iso():
    """Retorna o datetime atual em UTC em formato ISO."""
    return get_utc_now().isoformat()


def get_today():
    """Retorna a data atual no fuso horario da aplicacao."""
    return get_now().date()


def ensure_aware(dt: datetime, default_tz=APP_TZ) -> datetime:
    """Garante que um datetime tenha timezone."""
    if dt.tzinfo is None:
        return default_tz.localize(dt)
    return dt


def to_app_timezone(value: datetime) -> datetime:
    """Converte um datetime para o timezone da aplicacao."""
    return ensure_aware(value, UTC).astimezone(APP_TZ)


def unix_to_app_datetime(value: Any) -> datetime | None:
    """Converte unix epoch para datetime no timezone da aplicacao."""
    if value is None or value == '':
        return None

    try:
        timestamp = int(value)
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=UTC).astimezone(APP_TZ)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def unix_to_app_iso(value: Any) -> str | None:
    """Converte unix epoch para ISO com offset do timezone da aplicacao."""
    converted = unix_to_app_datetime(value)
    return converted.isoformat() if converted else None


def parse_datetime(value: Any) -> datetime | None:
    """Garante que um valor de data/hora seja convertido em datetime timezone-aware no timezone da aplicacao."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return ensure_aware(value)
    
    # Se for timestamp Unix (int ou float)
    if isinstance(value, (int, float)):
        return unix_to_app_datetime(value)
    
    text = str(value).strip()
    if not text or text.lower() in ("none", "null", "não informado", "nao informado", "-"):
        return None
        
    # Se for string numérica (timestamp Unix)
    if text.isdigit():
        try:
            return unix_to_app_datetime(int(text))
        except (ValueError, TypeError):
            pass

    import re

    # 1. Tentar ISO 8601 padrão
    try:
        t = text.replace("Z", "+00:00")
        # Se contiver espaço e não for offset, substitui por T
        if " " in t:
            parts = t.split(" ")
            if len(parts) == 2 and not ("+" in parts[1] or "-" in parts[1]):
                t = t.replace(" ", "T")
        # Caso o offset não tenha minutos, e.g. -03, ajusta para -03:00
        if re.search(r'[+-]\d{2}$', t):
            t += ':00'
        return ensure_aware(datetime.fromisoformat(t))
    except ValueError:
        pass

    # 2. Tentar formato brasileiro DD/MM/YYYY HH:MM:SS ou DD/MM/YYYY
    br_match = re.match(r'^(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$', text)
    if br_match:
        day, month, year, hour, minute, second = br_match.groups()
        hour = int(hour) if hour else 0
        minute = int(minute) if minute else 0
        second = int(second) if second else 0
        try:
            dt = datetime(int(year), int(month), int(day), hour, minute, second)
            return ensure_aware(dt)
        except ValueError:
            pass

    # 3. Formatos comuns adicionais via strptime
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y'):
        try:
            dt = datetime.strptime(text, fmt)
            return ensure_aware(dt)
        except ValueError:
            continue

    return None


def normalize_to_iso(value: Any) -> str | None:
    """Converte qualquer formato de data/hora em uma string ISO 8601 timezone-aware."""
    dt = parse_datetime(value)
    return dt.isoformat() if dt else None

