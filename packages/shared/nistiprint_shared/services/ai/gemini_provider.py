"""Provedor Gemini (google-genai)."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from nistiprint_shared.services.ai.base import AIProviderError, AIResponse

logger = logging.getLogger(__name__)

#: Modelos aceitos. O Gemini cobra por modelo inexistente com um 404 tardio,
#: entao vale barrar antes de gastar a chamada.
ALLOWED_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
)
DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: float = 60.0):
        self.model = model or DEFAULT_MODEL
        self._api_key = api_key or os.getenv("NISTIPRINT_AI_KEY")
        self._timeout = max(1.0, float(timeout))
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise AIProviderError(
                "NISTIPRINT_AI_KEY nao configurada — provedor gemini indisponivel"
            )
        try:
            from google import genai
        except Exception as exc:  # pragma: no cover - depende de ambiente
            raise AIProviderError(f"Falha ao importar cliente Gemini: {exc}") from exc

        from google.genai import types
        self._client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
        )
        return self._client

    def supports(self, model: str) -> bool:
        return model in ALLOWED_MODELS

    def complete(self, system_prompt: str, user_payload: str,
                 response_schema: Optional[dict] = None) -> AIResponse:
        client = self._get_client()
        prompt = f"{system_prompt}\n\n{user_payload}"

        started = time.monotonic()
        try:
            config = None
            if response_schema:
                from google.genai import types
                config = types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=response_schema,
                )
            response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        except Exception as exc:
            raise AIProviderError(f"Gemini falhou: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        text = getattr(response, "text", None)
        if not text:
            raise AIProviderError("Resposta vazia do Gemini")

        usage = None
        metadata = getattr(response, "usage_metadata", None)
        if metadata is not None:
            usage = {
                "prompt_tokens": getattr(metadata, "prompt_token_count", None),
                "completion_tokens": getattr(metadata, "candidates_token_count", None),
                "total_tokens": getattr(metadata, "total_token_count", None),
            }

        return AIResponse(
            text=text,
            provider=self.name,
            model_requested=self.model,
            model_used=self.model,
            usage=usage,
            latency_ms=latency_ms,
        )
