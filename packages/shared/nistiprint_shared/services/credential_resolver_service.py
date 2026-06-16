from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nistiprint_shared.services.integration_app_profile_service import (
    integration_app_profile_service,
)
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)


@dataclass(frozen=True)
class CredentialContext:
    module_id: str
    installation: dict
    app_profile: dict | None
    app_secrets: dict[str, str]
    installation_secrets: dict[str, str]
    config: dict
    credentials: dict

    @property
    def redirect_uri(self) -> str | None:
        if self.app_profile:
            return self.app_profile.get("redirect_uri")
        return None


class CredentialResolverService:
    def _find_legacy_value(self, installation: dict, *keys: str) -> str | None:
        config = installation.get("config") or {}
        credentials = installation.get("credentials") or {}
        legacy_credentials = installation.get("legacy_credentials") or {}
        legacy_credentials.update(installation.get("_legacy_credentials") or {})

        for container in (
            installation,
            config,
            credentials,
            legacy_credentials,
        ):
            if not isinstance(container, dict):
                continue
            for key in keys:
                value = container.get(key)
                if value not in (None, ""):
                    return value
        return None

    def resolve_for_installation(self, installation: dict) -> CredentialContext:
        module_id = str(installation.get("module_id") or "")
        app_profile_id = installation.get("app_profile_id")
        app_profile = None
        if app_profile_id:
            app_profile = integration_app_profile_service.get_profile(app_profile_id)
        if not app_profile:
            app_profile = integration_app_profile_service.get_default_profile(module_id)

        app_secrets = (
            integration_secret_service.get_secret_map("app_profile", app_profile["id"])
            if app_profile
            else {}
        )
        installation_id = installation.get("id")
        installation_secrets = (
            integration_secret_service.get_secret_map(
                "installed_integration", installation_id
            )
            if installation_id
            else {}
        )

        # Compatibility fallback while the backfill is still underway.
        for target, keys in (
            ("access_token", ("access_token",)),
            ("refresh_token", ("refresh_token",)),
            ("partner_id", ("partner_id", "app_id")),
            ("partner_key", ("partner_key", "app_secret", "secret")),
            ("client_id", ("client_id",)),
            ("client_secret", ("client_secret",)),
        ):
            if target not in installation_secrets and target in {"access_token", "refresh_token"}:
                legacy = self._find_legacy_value(installation, *keys)
                if legacy not in (None, ""):
                    installation_secrets[target] = legacy
            if target not in app_secrets and target not in {"access_token", "refresh_token"}:
                legacy = self._find_legacy_value(installation, *keys)
                if legacy not in (None, ""):
                    app_secrets[target] = legacy

        return CredentialContext(
            module_id=module_id,
            installation=installation,
            app_profile=app_profile,
            app_secrets=app_secrets,
            installation_secrets=installation_secrets,
            config=dict(installation.get("config") or {}),
            credentials=dict(installation.get("credentials") or {}),
        )

    def hydrate_integration(self, installation: dict) -> dict:
        context = self.resolve_for_installation(installation)
        hydrated = dict(installation)
        hydrated["config"] = {
            **context.config,
            **{
                key: value
                for key, value in context.app_secrets.items()
                if key not in {"access_token", "refresh_token"}
            },
        }
        hydrated["credentials"] = {
            **context.credentials,
            **context.installation_secrets,
        }
        if context.installation_secrets.get("access_token"):
            hydrated["access_token"] = context.installation_secrets["access_token"]
        if context.installation_secrets.get("refresh_token"):
            hydrated["refresh_token"] = context.installation_secrets["refresh_token"]
        if context.app_profile:
            hydrated["app_profile_id"] = context.app_profile["id"]
            hydrated["app_profile"] = context.app_profile
        return hydrated

    def persist_installation_tokens(
        self,
        installation_id: Any,
        tokens: dict[str, Any],
    ) -> None:
        if tokens.get("access_token") not in (None, ""):
            integration_secret_service.put_secret(
                "installed_integration",
                installation_id,
                "access_token",
                tokens["access_token"],
            )
        if tokens.get("refresh_token") not in (None, ""):
            integration_secret_service.rotate_secret(
                "installed_integration",
                installation_id,
                "refresh_token",
                tokens["refresh_token"],
            )

    def has_installation_token(self, installation: dict, secret_kind: str) -> bool:
        installation_id = installation.get("id")
        if installation_id and integration_secret_service.has_secret(
            "installed_integration", installation_id, secret_kind
        ):
            return True
        return self._find_legacy_value(installation, secret_kind) not in (None, "")


credential_resolver_service = CredentialResolverService()
