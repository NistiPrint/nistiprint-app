"""Resolucao de segredos de webhook a partir do banco.

O segredo com que o provider assina o webhook e o mesmo `client_secret` do
aplicativo que ja esta em `installed_integrations`. Ler esse valor de variavel
de ambiente cria uma segunda fonte de verdade que se desatualiza sozinha:
cadastrar uma conta nova pela interface faz o OAuth, o token e a API
funcionarem, e os webhooks dessa conta serem descartados em silencio.

Este modulo resolve os segredos do banco, com cache de processo, e mantem o
vinculo `conta do provider -> integracao instalada` para que a validacao use
**um** segredo em vez de todos.

Por que isso importa alem de performance: validar contra todos os segredos
significa que a conta A pode assinar um evento que se declara da conta B e ser
aceita. Resolver a conta antes de validar fecha esse buraco.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Valores que aparecem em `.env.example` e afins. Um placeholder e pior que a
#: ausencia do segredo: a lista fica nao-vazia, nenhuma assinatura bate e o
#: evento e descartado como invalido em vez de nao-verificado.
_PLACEHOLDERS = {
    "...", "…", "changeme", "change-me", "todo", "tbd", "xxx",
    "your-secret", "your_secret", "secret", "placeholder", "none", "null",
}

_MIN_SECRET_LENGTH = 8

#: Onde o `client_secret` mora em cada provider.
_MODULE_BY_SOURCE = {"bling": "bling", "mercadolivre": "mercadolivre", "shopee": "shopee"}

#: Chave em `installed_integrations.config` que guarda a identidade da conta no
#: provider, aprendida na primeira validacao bem-sucedida.
_ACCOUNT_KEYS = {
    "bling": "bling_company_id",
    "mercadolivre": "meli_user_id",
    "shopee": "shop_id",
}


@dataclass(frozen=True)
class SecretCandidate:
    secret: str
    integration_id: int | None
    account_id: str | None
    origin: str  # "db" | "env"


def is_usable_secret(value: Any) -> bool:
    """Placeholder e segredo curto demais nao contam como segredo."""
    text = str(value or "").strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return False
    return len(text) >= _MIN_SECRET_LENGTH


def account_id_from_payload(source: str, payload: dict[str, Any]) -> str | None:
    """Identidade da conta declarada pelo proprio evento, quando existir."""
    if not isinstance(payload, dict):
        return None
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    source = str(source or "").lower()
    if source == "bling":
        value = payload.get("companyId") or body.get("companyId")
    elif source == "mercadolivre":
        value = body.get("user_id") or payload.get("user_id")
    elif source == "shopee":
        content = body.get("content") if isinstance(body.get("content"), dict) else {}
        value = content.get("shop_id") or body.get("shop_id") or payload.get("shop_id")
    else:
        value = None
    text = str(value or "").strip()
    return text or None


class WebhookSecretResolver:
    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, list[SecretCandidate]] = {}
        self._loaded_at: dict[str, float] = {}

    # -- API ---------------------------------------------------------------- #

    def candidates(
        self,
        source: str,
        *,
        account_hint: str | None = None,
        env_secrets: Iterable[str] = (),
    ) -> list[SecretCandidate]:
        """Segredos a testar, com a conta declarada pelo evento na frente."""
        source = str(source or "").lower()
        found = list(self._from_db(source))

        known = [c for c in found if c.account_id]
        if account_hint and known:
            matching = [c for c in found if c.account_id == account_hint]
            if matching:
                # Conta conhecida: valida contra ela e mais nada.
                return matching

        env = [
            SecretCandidate(str(value).strip(), None, None, "env")
            for value in env_secrets
            if is_usable_secret(value)
        ]
        seen: set[str] = set()
        ordered: list[SecretCandidate] = []
        for candidate in [*found, *env]:
            if candidate.secret in seen:
                continue
            seen.add(candidate.secret)
            ordered.append(candidate)
        return ordered

    def remember_account(
        self, source: str, account_id: str | None, integration_id: int | None
    ) -> None:
        """Grava o vinculo aprendido para que a proxima validacao seja direta."""
        source = str(source or "").lower()
        key = _ACCOUNT_KEYS.get(source)
        if not (key and account_id and integration_id):
            return
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db

            rows = (
                supabase_db.table("installed_integrations")
                .select("config")
                .eq("id", integration_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            config = (rows[0].get("config") if rows else None) or {}
            if not isinstance(config, dict):
                config = {}
            if str(config.get(key) or "") == str(account_id):
                return
            config[key] = str(account_id)
            supabase_db.table("installed_integrations").update(
                {"config": config}
            ).eq("id", integration_id).execute()
            logger.info(
                "[webhook-secret] vinculo aprendido source=%s conta=%s integracao=%s",
                source, account_id, integration_id,
            )
        except Exception as exc:  # pragma: no cover - aprendizado e best effort
            logger.warning("[webhook-secret] falha ao gravar vinculo: %s", exc)
            return
        self.invalidate(source)

    def invalidate(self, source: str | None = None) -> None:
        with self._lock:
            if source is None:
                self._cache.clear()
                self._loaded_at.clear()
            else:
                self._cache.pop(source, None)
                self._loaded_at.pop(source, None)

    # -- interno ------------------------------------------------------------ #

    def _from_db(self, source: str) -> list[SecretCandidate]:
        now = time.monotonic()
        with self._lock:
            if source in self._cache and (now - self._loaded_at.get(source, 0)) < self._ttl:
                return self._cache[source]
        loaded = self._load(source)
        with self._lock:
            self._cache[source] = loaded
            self._loaded_at[source] = now
        return loaded

    def _load(self, source: str) -> list[SecretCandidate]:
        module_id = _MODULE_BY_SOURCE.get(source)
        if not module_id:
            return []
        account_key = _ACCOUNT_KEYS.get(source)
        try:
            from nistiprint_shared.database.supabase_db_service import supabase_db

            rows = (
                supabase_db.table("installed_integrations")
                .select("id,credentials,config")
                .eq("module_id", module_id)
                .eq("is_active", True)
                .execute()
                .data
                or []
            )
        except Exception as exc:  # pragma: no cover - degradacao auditavel
            logger.warning(
                "[webhook-secret] banco indisponivel para %s, usando apenas env: %s",
                source, exc,
            )
            return []

        candidates: list[SecretCandidate] = []
        for row in rows if isinstance(rows, list) else []:
            credentials = row.get("credentials") or {}
            if not isinstance(credentials, dict):
                continue
            secret = credentials.get("client_secret")
            if not is_usable_secret(secret):
                continue
            config = row.get("config") if isinstance(row.get("config"), dict) else {}
            account_id = str(config.get(account_key) or "").strip() or None
            candidates.append(
                SecretCandidate(str(secret).strip(), row.get("id"), account_id, "db")
            )
        if not candidates:
            logger.warning(
                "[webhook-secret] nenhuma integracao ativa de %s com client_secret utilizavel",
                source,
            )
        return candidates


webhook_secret_resolver = WebhookSecretResolver()
