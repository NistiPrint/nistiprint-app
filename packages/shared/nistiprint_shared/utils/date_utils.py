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
