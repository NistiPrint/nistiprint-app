"""Roteamento de provedores de modelo de linguagem."""
from nistiprint_shared.services.ai.base import (
    AIProvider,
    AIProviderError,
    AIResponse,
    AIResponseParseError,
    extract_json,
)
from nistiprint_shared.services.ai.router import (
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_PROVIDER,
    PROVIDERS,
    AIRouter,
    ai_router,
    build_provider,
    validate_model,
)

__all__ = [
    "AIProvider",
    "AIProviderError",
    "AIResponse",
    "AIResponseParseError",
    "AIRouter",
    "DEFAULT_MODEL_BY_PROVIDER",
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "ai_router",
    "build_provider",
    "extract_json",
    "validate_model",
]
