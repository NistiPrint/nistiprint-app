"""Shared authentication helpers for the Bling API."""

import base64
import binascii
import json
import re

BLING_JWT_HEADER = "enable-jwt"
BLING_JWT_HEADER_VALUE = "1"


def _is_json_object_segment(segment: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        return False
    padded = segment + "=" * (-len(segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        return isinstance(json.loads(decoded), dict)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False


def is_bling_jwt(token: str | None) -> bool:
    """Check compact JWT structure without trusting or verifying its claims."""
    if not isinstance(token, str):
        return False
    parts = token.split(".")
    return (
        len(parts) == 3
        and all(parts)
        and _is_json_object_segment(parts[0])
        and _is_json_object_segment(parts[1])
        and bool(re.fullmatch(r"[A-Za-z0-9_-]+", parts[2]))
    )


def require_bling_jwt(token: str | None) -> str:
    """Reject opaque or malformed access tokens before they replace valid ones."""
    if not is_bling_jwt(token):
        raise ValueError("Bling nao retornou um access_token JWT valido.")
    return token
