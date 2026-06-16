from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CredentialStrategy:
    auth_type: str
    management_mode: str
    source_system: str | None
    supports_refresh: bool
    supports_healthcheck: bool
    supports_external_sync: bool
    identity_label: str | None


class IntegrationCredentialsService:
    def strategy_for(self, installation: dict) -> CredentialStrategy:
        module_id = str(installation.get("module_id") or "").lower()
        if module_id == "bling":
            return CredentialStrategy(
                auth_type="oauth2",
                management_mode="external_sync",
                source_system="firebase",
                supports_refresh=False,
                supports_healthcheck=True,
                supports_external_sync=True,
                identity_label="CNPJ",
            )
        if "shopee" in module_id:
            return CredentialStrategy(
                auth_type="oauth2",
                management_mode="app_managed",
                source_system="supabase",
                supports_refresh=True,
                supports_healthcheck=True,
                supports_external_sync=False,
                identity_label="Shop ID",
            )
        if module_id == "mercadolivre":
            return CredentialStrategy(
                auth_type="oauth2",
                management_mode="app_managed",
                source_system="supabase",
                supports_refresh=True,
                supports_healthcheck=True,
                supports_external_sync=False,
                identity_label="User ID",
            )
        return CredentialStrategy(
            auth_type="none",
            management_mode="not_required",
            source_system=None,
            supports_refresh=False,
            supports_healthcheck=False,
            supports_external_sync=False,
            identity_label=None,
        )

    def public_view(self, installation: dict) -> dict:
        strategy = self.strategy_for(installation)
        credentials = installation.get("credentials") or {}
        config = installation.get("config") or {}
        expires_at = _parse_dt(installation.get("expires_at"))
        last_sync = _parse_dt(installation.get("last_sync"))
        last_refresh_attempt = _parse_dt(installation.get("last_refresh_attempt"))
        last_updated = _parse_dt(installation.get("updated_at"))
        has_access_token = credential_resolver_service.has_installation_token(
            installation, "access_token"
        )
        has_refresh_token = credential_resolver_service.has_installation_token(
            installation, "refresh_token"
        )
        token_status = self._token_status(
            strategy=strategy,
            has_access_token=has_access_token,
            has_refresh_token=has_refresh_token,
            expires_at=expires_at,
            refresh_error=installation.get("refresh_error"),
            last_sync=last_sync,
            last_updated=last_updated,
        )
        connection_status = self._connection_status(strategy, installation)

        account_identifier = (
            (config.get("account_identifiers") or {}).get("primary")
            or config.get("shop_id")
            or config.get("seller_id")
            or config.get("user_id")
            or config.get("account_id")
            or config.get("cnpj")
            or (credentials.get("account_identifiers") or {}).get("primary")
            or credentials.get("shop_id")
            or credentials.get("seller_id")
            or credentials.get("user_id")
            or credentials.get("account_id")
        )

        return {
            "auth_type": strategy.auth_type,
            "management_mode": strategy.management_mode,
            "source_system": strategy.source_system,
            "supports_refresh": strategy.supports_refresh,
            "supports_healthcheck": strategy.supports_healthcheck,
            "supports_external_sync": strategy.supports_external_sync,
            "token_status": token_status,
            "connection_status": connection_status,
            "account_identifier": str(account_identifier) if account_identifier not in (None, "") else None,
            "account_identifier_label": strategy.identity_label,
            "has_access_token": has_access_token,
            "has_refresh_token": has_refresh_token,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "last_sync": last_sync.isoformat() if last_sync else None,
            "last_refresh_attempt": last_refresh_attempt.isoformat() if last_refresh_attempt else None,
            "last_updated": last_updated.isoformat() if last_updated else None,
            "refresh_error": installation.get("refresh_error"),
            "actions": {
                "can_refresh": strategy.supports_refresh,
                "can_sync_external": strategy.supports_external_sync,
                "can_test_connection": strategy.supports_healthcheck and has_access_token,
            },
        }

    def sanitize_installation(self, installation: dict) -> dict:
        public = dict(installation)
        credentials = dict(public.get("credentials") or {})
        for key in (
            "access_token",
            "refresh_token",
            "client_secret",
            "partner_key",
            "authorization",
            "token",
        ):
            credentials.pop(key, None)
        public.pop("access_token", None)
        public.pop("refresh_token", None)
        public["credentials"] = credentials
        public["credential_status"] = self.public_view(installation)
        return public

    def ensure_refresh_allowed(self, installation: dict) -> None:
        strategy = self.strategy_for(installation)
        if strategy.management_mode == "external_sync":
            raise ValueError(
                "Credencial gerenciada por sincronizacao externa. Use a sincronizacao da fonte externa."
            )
        if not strategy.supports_refresh:
            raise ValueError("Esta integracao nao suporta renovacao local de credenciais.")

    def _token_status(
        self,
        *,
        strategy: CredentialStrategy,
        has_access_token: bool,
        has_refresh_token: bool,
        expires_at: datetime | None,
        refresh_error: str | None,
        last_sync: datetime | None,
        last_updated: datetime | None,
    ) -> str:
        if strategy.management_mode == "not_required":
            return "not_required"
        if not has_access_token:
            return "missing"

        now = _now_utc()
        if strategy.management_mode == "external_sync":
            if last_updated and now - last_updated > timedelta(days=2):
                return "external_sync_stale"
            if expires_at and expires_at <= now:
                return "expired"
            if refresh_error:
                return "external_sync_warning"
            if expires_at and expires_at <= now + timedelta(hours=6):
                return "expiring_soon"
            return "valid"

        if refresh_error and not has_refresh_token:
            return "reauth_required"
        if refresh_error and expires_at and expires_at <= now:
            return "refresh_failed"
        if expires_at and expires_at <= now:
            return "expired"
        if expires_at and expires_at <= now + timedelta(hours=24):
            return "expiring_soon"
        if refresh_error:
            return "refresh_warning"
        if last_sync and now - last_sync > timedelta(days=7):
            return "stale"
        return "valid"

    def _connection_status(self, strategy: CredentialStrategy, installation: dict) -> str:
        if not strategy.supports_healthcheck:
            return "not_applicable"
        sync_status = str(installation.get("sync_status") or "").lower()
        refresh_error = installation.get("refresh_error")
        if sync_status in {"error", "failed"}:
            return "failed"
        if refresh_error:
            return "degraded"
        if sync_status in {"active", "success"}:
            return "healthy"
        return "untested"


integration_credentials_service = IntegrationCredentialsService()
