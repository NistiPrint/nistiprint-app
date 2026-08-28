from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from nistiprint_shared.services.integration_app_profile_service import (
    integration_app_profile_service,
)
from nistiprint_shared.services.integration_provider_registry import (
    get_provider_spec,
)
from nistiprint_shared.services.integration_secret_service import (
    integration_secret_service,
)


logger = logging.getLogger(__name__)

#: Modulos cujo par client_id/client_secret ainda pode vir do ambiente enquanto
#: nenhum app profile existir para eles. E uma rampa de migracao, nao um modo de
#: operacao: assim que o primeiro profile do modulo e cadastrado, o ambiente
#: deixa de ser consultado para sempre.
_LEGACY_ENV_BOOTSTRAP_MODULES = {"mercadolivre"}

#: Aviso de bootstrap e uma vez por modulo, nao por chamada.
_WARNED_LEGACY_BOOTSTRAP: set[str] = set()

#: Prefixo historico da variavel de ambiente, por modulo.
_LEGACY_ENV_PREFIXES = {"mercadolivre": "ML_CNPJ01_"}


class AmbiguousAppProfileError(RuntimeError):
    """A instalacao nao diz qual aplicativo usar e ha mais de um candidato.

    Levantar aqui e deliberado. O caminho alternativo — herdar o profile padrao
    do modulo — assina a renovacao com o aplicativo de outra conta; no Mercado
    Livre isso devolve `invalid_grant` e, como o refresh token e rotativo, a
    tentativa consome a credencial da conta e exige reautorizacao manual.
    """

    error_type = "app_profile_ambiguous"

    def __init__(self, module_id: str, candidates: list[Any]):
        self.module_id = module_id
        self.candidate_ids = [row.get("id") for row in candidates if isinstance(row, dict)]
        super().__init__(
            f"Instalacao de {module_id} sem app_profile_id definido e "
            f"{len(self.candidate_ids)} aplicativos ativos ({self.candidate_ids}). "
            "Vincule a instalacao ao aplicativo correto antes de usar a credencial."
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

    def _resolve_app_profile(self, installation: dict, module_id: str) -> dict | None:
        """Aplicativo OAuth desta instalacao, sem nunca escolher por conta propria.

        Ordem:
          1. `app_profile_id` da instalacao — sempre vence;
          2. profile unico ativo do modulo — nao ha o que escolher;
          3. varios profiles e nenhum vinculo — erro, nunca palpite;
          4. nenhum profile — devolve None e deixa o bootstrap por ambiente agir.
        """
        app_profile_id = installation.get("app_profile_id")
        if app_profile_id:
            profile = integration_app_profile_service.get_profile(app_profile_id)
            if profile:
                return profile
            logger.warning(
                "[credenciais] instalacao %s aponta para app_profile_id=%s inexistente; "
                "resolvendo pelo modulo",
                installation.get("id"), app_profile_id,
            )

        candidates = [
            row
            for row in integration_app_profile_service.list_profiles(module_id=module_id)
            if row.get("is_active")
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise AmbiguousAppProfileError(module_id, candidates)
        return None

    def resolve_for_installation(self, installation: dict) -> CredentialContext:
        module_id = str(installation.get("module_id") or "")
        provider_spec = get_provider_spec(module_id)
        app_profile = self._resolve_app_profile(installation, module_id)

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
        for target in ("access_token", "refresh_token"):
            if target not in installation_secrets:
                legacy = self._find_legacy_value(installation, target)
                if legacy not in (None, ""):
                    installation_secrets[target] = legacy

        if provider_spec:
            for field in provider_spec.app_profile_secret_fields:
                if field.secret_kind in app_secrets:
                    continue
                legacy = self._find_legacy_value(
                    installation, field.secret_kind, *field.aliases
                )
                if legacy not in (None, ""):
                    app_secrets[field.secret_kind] = legacy

        if app_profile is None:
            app_secrets.update(self._legacy_env_bootstrap(module_id, app_secrets))

        return CredentialContext(
            module_id=module_id,
            installation=installation,
            app_profile=app_profile,
            app_secrets=app_secrets,
            installation_secrets=installation_secrets,
            config=dict(installation.get("config") or {}),
            credentials=dict(installation.get("credentials") or {}),
        )

    def _legacy_env_bootstrap(self, module_id: str, app_secrets: dict) -> dict[str, str]:
        """Par client_id/secret do ambiente, so enquanto o modulo nao tem profile.

        Existe para que o deploy que endurece esta resolucao nao derrube uma
        integracao que ainda nao foi migrada: sem nenhum profile cadastrado nao
        ha ambiguidade possivel, entao o valor do ambiente ainda e seguro. Com
        um profile cadastrado, este metodo nunca e alcancado.
        """
        if module_id not in _LEGACY_ENV_BOOTSTRAP_MODULES:
            return {}

        prefix = _LEGACY_ENV_PREFIXES.get(module_id)
        if not prefix:
            return {}

        resolved: dict[str, str] = {}
        for secret_kind, suffix in (("client_id", "CLIENT_ID"), ("client_secret", "CLIENT_SECRET")):
            if app_secrets.get(secret_kind) not in (None, ""):
                continue
            value = os.getenv(f"{prefix}{suffix}")
            if value not in (None, ""):
                resolved[secret_kind] = value

        if resolved and module_id not in _WARNED_LEGACY_BOOTSTRAP:
            _WARNED_LEGACY_BOOTSTRAP.add(module_id)
            logger.warning(
                "[credenciais] %s ainda usa credencial de aplicativo vinda do ambiente "
                "(%s*). Cadastre o app profile do modulo: enquanto isso, uma segunda "
                "conta nao pode ser autorizada com seguranca.",
                module_id, prefix,
            )
        return resolved

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
