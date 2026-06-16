"""Helpers for marketplace account identity used by webhook routing."""

from __future__ import annotations

from typing import Any


LEGACY_IDENTITY_FIELDS = (
    "shop_id",
    "shopid",
    "seller_id",
    "user_id",
    "account_id",
    "bling_loja_id",
)


def normalize_account_identifier(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    return normalized or None


def account_identity_kind(module_id: str | None) -> str:
    module = str(module_id or "").lower()
    if "shopee" in module:
        return "shop_id"
    if module == "mercadolivre" or "mercadolivre" in module or "mercado_livre" in module:
        return "user_id"
    if "amazon" in module:
        return "seller_id"
    return "account_id"


def build_account_identifiers(
    module_id: str | None,
    primary: Any,
    *,
    aliases: list[Any] | tuple[Any, ...] | None = None,
    source: str = "manual",
    kind: str | None = None,
) -> dict | None:
    normalized_primary = normalize_account_identifier(primary)
    if not normalized_primary:
        return None

    normalized_aliases = []
    seen = {normalized_primary}
    for alias in aliases or []:
        normalized = normalize_account_identifier(alias)
        if normalized and normalized not in seen:
            normalized_aliases.append(normalized)
            seen.add(normalized)

    return {
        "primary": normalized_primary,
        "kind": kind or account_identity_kind(module_id),
        "aliases": normalized_aliases,
        "source": source or "manual",
    }


def merge_account_identity_config(
    config: dict | None,
    module_id: str | None,
    identifier: Any,
    *,
    source: str = "manual",
    kind: str | None = None,
    aliases: list[Any] | tuple[Any, ...] | None = None,
) -> dict:
    updated = dict(config or {})
    account_identifiers = build_account_identifiers(
        module_id,
        identifier,
        aliases=aliases,
        source=source,
        kind=kind,
    )
    if not account_identifiers:
        return updated

    updated["account_identifiers"] = account_identifiers
    legacy_field = account_identifiers["kind"]
    if legacy_field in ("shop_id", "seller_id", "user_id", "account_id"):
        updated[legacy_field] = account_identifiers["primary"]
    return updated


def extract_account_identifiers(config: dict | None = None, credentials: dict | None = None) -> set[str]:
    identifiers: set[str] = set()

    for container in (config or {}, credentials or {}):
        account_identifiers = container.get("account_identifiers") if isinstance(container, dict) else None
        if isinstance(account_identifiers, dict):
            primary = normalize_account_identifier(account_identifiers.get("primary"))
            if primary:
                identifiers.add(primary)
            for alias in account_identifiers.get("aliases") or []:
                normalized = normalize_account_identifier(alias)
                if normalized:
                    identifiers.add(normalized)

        if isinstance(container, dict):
            for field in LEGACY_IDENTITY_FIELDS:
                normalized = normalize_account_identifier(container.get(field))
                if normalized:
                    identifiers.add(normalized)
            for value in container.get("shop_ids") or []:
                normalized = normalize_account_identifier(value)
                if normalized:
                    identifiers.add(normalized)

    return identifiers


def integration_account_identifiers(integration: dict | Any | None) -> set[str]:
    if not integration:
        return set()

    if isinstance(integration, dict):
        config = integration.get("config") or {}
        credentials = integration.get("credentials") or {}
    else:
        config = getattr(integration, "config", None) or {}
        credentials = getattr(integration, "credentials", None) or {}

    return extract_account_identifiers(config=config, credentials=credentials)


def has_account_identity(integration: dict | Any | None) -> bool:
    return bool(integration_account_identifiers(integration))


def account_identity_matches(integration: dict | Any | None, identifier: Any) -> bool:
    normalized = normalize_account_identifier(identifier)
    if not normalized:
        return False
    return normalized in integration_account_identifiers(integration)
