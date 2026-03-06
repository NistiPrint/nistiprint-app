from datetime import datetime
import pytz
from nistiprint_shared.constants import APP_TIMEZONE

def get_now():
    """Retorna o datetime atual no fuso horário da aplicação."""
    tz = pytz.timezone(APP_TIMEZONE)
    return datetime.now(tz)

def get_now_iso():
    """Retorna o datetime atual em formato ISO com fuso horário."""
    return get_now().isoformat()

def get_today():
    """Retorna a data atual no fuso horário da aplicação."""
    return get_now().date()
