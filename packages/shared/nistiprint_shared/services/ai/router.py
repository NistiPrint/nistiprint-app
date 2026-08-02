"""Roteador de provedores de IA.

Escolhe o provedor por configuracao (`configuracoes_aplicacao`, categoria `ia`),
com fallback opcional. Nenhuma chave de API vive em banco: elas continuam em
variavel de ambiente, e o banco guarda apenas *qual* provedor e *qual* modelo.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nistiprint_shared.services.ai.base import AIProvider, AIProviderError, AIResponse
from nistiprint_shared.services.ai.gemini_provider import (
    ALLOWED_MODELS as GEMINI_MODELS,
    DEFAULT_MODEL as GEMINI_DEFAULT,
    GeminiProvider,
)
from nistiprint_shared.services.ai.openrouter_provider import (
    DEFAULT_MODEL as OPENROUTER_DEFAULT,
    OpenRouterProvider,
)

logger = logging.getLogger(__name__)

PROVIDERS = ("gemini", "openrouter")
DEFAULT_PROVIDER = "gemini"

DEFAULT_MODEL_BY_PROVIDER = {
    "gemini": GEMINI_DEFAULT,
    "openrouter": OPENROUTER_DEFAULT,
}

CONFIG_KEYS = {
    "provider": "ia_provider",
    "model": "ia_model",
    "fallback_provider": "ia_fallback_provider",
    "timeout": "ia_timeout_seconds",
}


def _normalize(value: Any) -> str:
    return str(value or "").strip().strip('"').lower()


def build_provider(
    provider_name: str, model: Optional[str] = None, timeout: float = 60.0
) -> AIProvider:
    name = _normalize(provider_name) or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise AIProviderError(f"Provedor de IA desconhecido: {provider_name!r}")

    effective_model = (model or "").strip() or DEFAULT_MODEL_BY_PROVIDER[name]

    if name == "gemini":
        if effective_model not in GEMINI_MODELS:
            raise AIProviderError(
                f"Modelo {effective_model!r} nao e valido para o Gemini. "
                f"Aceitos: {', '.join(GEMINI_MODELS)}"
            )
        return GeminiProvider(model=effective_model)

    provider = OpenRouterProvider(model=effective_model, timeout=timeout)
    if not provider.supports(effective_model):
        raise AIProviderError(
            f"Modelo {effective_model!r} nao tem formato valido para OpenRouter "
            "(esperado 'openrouter/auto' ou 'vendor/model')"
        )
    return provider


def validate_model(provider_name: str, model: str) -> None:
    """Levanta `AIProviderError` se o par provedor/modelo for invalido."""
    build_provider(provider_name, model)


class AIRouter:
    """Ponto unico de chamada ao modelo."""

    def __init__(self, config_reader=None):
        # Injetavel para teste; por padrao le a configuracao da aplicacao.
        self._config_reader = config_reader

    def _get_config(self, key: str, default: Any = None) -> Any:
        if self._config_reader is not None:
            return self._config_reader(key, default)
        from nistiprint_shared.services.app_config_service import app_config_service

        value = app_config_service.get_config(key)
        return default if value in (None, "") else value

    def resolve_settings(self) -> Dict[str, Any]:
        provider = _normalize(self._get_config(CONFIG_KEYS["provider"], DEFAULT_PROVIDER))
        if provider not in PROVIDERS:
            logger.warning(
                "ia_provider=%r desconhecido; usando %s", provider, DEFAULT_PROVIDER
            )
            provider = DEFAULT_PROVIDER

        model = self._get_config(CONFIG_KEYS["model"], None)
        model = str(model).strip().strip('"') if model else DEFAULT_MODEL_BY_PROVIDER[provider]

        fallback = _normalize(self._get_config(CONFIG_KEYS["fallback_provider"], "")) or None
        if fallback and fallback not in PROVIDERS:
            logger.warning("ia_fallback_provider=%r desconhecido; ignorando", fallback)
            fallback = None
        if fallback == provider:
            fallback = None

        try:
            timeout = float(self._get_config(CONFIG_KEYS["timeout"], 60) or 60)
        except (TypeError, ValueError):
            timeout = 60.0

        return {
            "provider": provider,
            "model": model,
            "fallback_provider": fallback,
            "timeout_seconds": timeout,
        }

    def complete(self, system_prompt: str, user_payload: str) -> AIResponse:
        settings = self.resolve_settings()
        primary = build_provider(
            settings["provider"], settings["model"], settings["timeout_seconds"]
        )

        try:
            return primary.complete(system_prompt, user_payload)
        except AIProviderError as exc:
            fallback_name = settings["fallback_provider"]
            if not fallback_name:
                raise
            logger.warning(
                "Provedor %s falhou (%s); tentando fallback %s",
                settings["provider"],
                exc,
                fallback_name,
            )
            # O fallback usa o modelo default do proprio provedor: o modelo
            # configurado pertence ao primario e quase nunca existe no outro.
            fallback = build_provider(
                fallback_name,
                DEFAULT_MODEL_BY_PROVIDER[fallback_name],
                settings["timeout_seconds"],
            )
            return fallback.complete(system_prompt, user_payload)


ai_router = AIRouter()
