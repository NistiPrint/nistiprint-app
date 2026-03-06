from datetime import datetime
import logging

def refresh_token(integration: dict) -> dict:
    """
    Driver genérico para integrações que usam API Key fixa (sem refresh).
    Apenas atualiza o timestamp de verificação.
    """
    return {
        "updated_at": datetime.utcnow().isoformat(),
        "last_refresh_attempt": datetime.utcnow().isoformat(),
        "refresh_error": None
    }

