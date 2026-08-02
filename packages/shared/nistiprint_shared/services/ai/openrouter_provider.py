"""Provedor OpenRouter — API compativel com o formato chat/completions.

Suporta `openrouter/auto`, em que o roteamento de modelo e do proprio
OpenRouter. Esse e o modo usado no legado e o motivo de o campo `model_used`
existir no `AIResponse`: com `auto`, so a resposta diz quem atendeu.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from nistiprint_shared.services.ai.base import AIProviderError, AIResponse

logger = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/auto"


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 60.0,
        app_url: Optional[str] = None,
        app_title: Optional[str] = None,
    ):
        self.model = model or DEFAULT_MODEL
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self._client = client
        self._timeout = timeout
        # Cabecalhos de atribuicao do OpenRouter: opcionais, mas e por eles que
        # a conta identifica de onde veio o trafego.
        self._app_url = app_url or os.getenv("OPENROUTER_APP_URL", "https://nistiprint.local")
        self._app_title = app_title or os.getenv("OPENROUTER_APP_TITLE", "NistiPrint")

    def supports(self, model: str) -> bool:
        """Aceita `openrouter/auto` e qualquer `vendor/model`.

        Nao existe allowlist util aqui: o catalogo do OpenRouter muda toda
        semana, e uma lista fixa no codigo viraria bloqueio em vez de protecao.
        A validacao possivel e de forma.
        """
        if not model:
            return False
        return model == DEFAULT_MODEL or "/" in model

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self._timeout, connect=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    def complete(self, system_prompt: str, user_payload: str) -> AIResponse:
        if not self._api_key:
            raise AIProviderError(
                "OPENROUTER_API_KEY nao configurada — provedor openrouter indisponivel"
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._app_url,
            "X-Title": self._app_title,
        }

        started = time.monotonic()
        try:
            response = self._http().post(API_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AIProviderError(f"OpenRouter inacessivel: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            # O corpo do erro do OpenRouter costuma dizer exatamente o que
            # faltou (credito, modelo, permissao). Truncado para nao poluir log.
            raise AIProviderError(
                f"OpenRouter respondeu {response.status_code}: {response.text[:300]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise AIProviderError("OpenRouter devolveu corpo nao-JSON") from exc

        if body.get("error"):
            raise AIProviderError(f"OpenRouter: {str(body['error'])[:300]}")

        choices = body.get("choices") or []
        if not choices:
            raise AIProviderError("OpenRouter devolveu resposta sem choices")

        text = ((choices[0] or {}).get("message") or {}).get("content")
        if not text:
            raise AIProviderError("OpenRouter devolveu conteudo vazio")

        return AIResponse(
            text=text,
            provider=self.name,
            model_requested=self.model,
            model_used=body.get("model"),
            usage=body.get("usage"),
            latency_ms=latency_ms,
            raw={"id": body.get("id")},
        )
