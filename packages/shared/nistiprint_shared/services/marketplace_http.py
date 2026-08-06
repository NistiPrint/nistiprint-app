"""Consistent HTTP result handling for marketplace provider clients."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable

import requests

from nistiprint_shared.services.marketplace_contracts import ProviderCallResult


DEFAULT_TIMEOUT = (3.05, 15.0)
SENSITIVE_KEYS = {
    "access_token", "refresh_token", "token", "authorization", "sign",
    "signature", "partner_key", "phone", "email", "address",
    "receiver_address", "recipient_address", "buyer", "payer",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _redact(nested)
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact(nested) for nested in value[:20]]
    if isinstance(value, str):
        return value[:500]
    return value


def _retry_after(headers: Any) -> float | None:
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        if value in (None, ""):
            return None
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            parsed = parsedate_to_datetime(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(1.0, (parsed - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _http_error(status: int) -> tuple[str, bool]:
    if status == 400:
        return "provider_parameter_error", False
    if status == 401:
        return "credential_action_required", False
    if status == 403:
        return "provider_access_forbidden", False
    if status == 404:
        return "provider_resource_not_found", False
    if status == 429:
        return "provider_rate_limited", True
    if status >= 500:
        return "provider_server_error", True
    return "provider_http_error", False


def request_json(
    send: Callable[..., Any],
    url: str,
    *,
    provider: str,
    resource_type: str,
    resource_id: str | None = None,
    success_statuses: Iterable[int] = (200,),
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    list_key: str | None = None,
    **kwargs,
) -> ProviderCallResult[dict]:
    try:
        response = send(url, timeout=timeout, **kwargs)
    except requests.Timeout as exc:
        return ProviderCallResult(
            False, provider=provider, resource_type=resource_type,
            resource_id=resource_id, error_type="provider_timeout",
            message=str(exc) or f"Timeout na API {provider}", retryable=True,
        )
    except requests.RequestException as exc:
        return ProviderCallResult(
            False, provider=provider, resource_type=resource_type,
            resource_id=resource_id, error_type="provider_network_error",
            message=str(exc) or f"Falha de rede na API {provider}", retryable=True,
        )

    status = int(response.status_code)
    if status not in set(success_statuses):
        error_type, retryable = _http_error(status)
        provider_payload = None
        try:
            candidate = response.json()
            provider_payload = _redact(candidate) if isinstance(candidate, (dict, list)) else None
        except (ValueError, requests.JSONDecodeError):
            provider_payload = None
        provider_code = None
        if isinstance(provider_payload, dict):
            provider_code = provider_payload.get("code") or provider_payload.get("error")
        return ProviderCallResult(
            False, provider=provider, resource_type=resource_type,
            resource_id=resource_id, status_code=status,
            provider_code=str(provider_code) if provider_code is not None else None,
            error_type=error_type,
            message=f"Erro na API {provider}: {status}",
            retryable=retryable, retry_after=_retry_after(response.headers),
            details=provider_payload,
        )
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        return ProviderCallResult(
            False, provider=provider, resource_type=resource_type,
            resource_id=resource_id, status_code=status,
            error_type="provider_invalid_response",
            message=str(exc) or f"Resposta JSON invalida da API {provider}",
            retryable=True,
        )
    if isinstance(data, list) and list_key:
        # Alguns recursos do provider respondem com array no root
        # (ex.: GET /shipments/{id}/items). Envelopamos para manter o
        # contrato de dict deste helper sem perder os elementos.
        data = {list_key: data}
    if not isinstance(data, dict):
        return ProviderCallResult(
            False, provider=provider, resource_type=resource_type,
            resource_id=resource_id, status_code=status,
            error_type="provider_invalid_response",
            message=f"Resposta inesperada da API {provider}",
            retryable=True,
        )
    return ProviderCallResult(
        True, value=data, provider=provider, resource_type=resource_type,
        resource_id=resource_id, status_code=status, partial=status == 206,
    )
