"""Contrato comum entre provedores de modelo.

Um provedor recebe prompt e devolve texto. Tudo o que e especifico de fornecedor
— formato de payload, nome do campo de resposta, cabecalhos de atribuicao —
morre dentro do provedor. Quem chama nao deve precisar saber qual esta ativo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol


class AIProviderError(RuntimeError):
    """Falha atribuivel ao provedor: credencial, transporte, resposta vazia."""


class AIResponseParseError(AIProviderError):
    """O modelo respondeu, mas nao em JSON utilizavel."""


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str
    model_requested: str
    #: Modelo realmente usado. Com `openrouter/auto` o roteamento e do
    #: OpenRouter, entao so a resposta revela quem atendeu. Sem guardar isso,
    #: nao se consegue explicar depois por que dois pedidos parecidos sairam
    #: diferentes.
    model_used: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    latency_ms: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_requested": self.model_requested,
            "model_used": self.model_used,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
        }


class AIProvider(Protocol):
    name: str

    def complete(self, system_prompt: str, user_payload: str) -> AIResponse: ...


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extrai o primeiro objeto JSON valido da resposta do modelo.

    O tratamento anterior era `replace("```json","").replace("```","")` seguido
    de `json.loads`. Funciona quando o modelo responde exatamente como pedido e
    quebra em tudo mais: prosa antes do JSON, dois blocos, cerca sem rotulo.
    Trocar de provedor multiplica esses casos, porque cada modelo tem seu vicio
    de formatacao.
    """
    if not text or not text.strip():
        raise AIResponseParseError("Resposta vazia do modelo")

    candidatos = []
    fenced = _JSON_FENCE.findall(text)
    candidatos.extend(fenced)
    candidatos.append(text.strip())

    for candidato in candidatos:
        candidato = candidato.strip()
        if not candidato:
            continue
        try:
            return json.loads(candidato)
        except json.JSONDecodeError:
            pass
        # Ultimo recurso: recorta do primeiro `{`/`[` ate o fechamento
        # correspondente, o que resolve prosa em volta do JSON.
        for abre, fecha in (("{", "}"), ("[", "]")):
            inicio = candidato.find(abre)
            fim = candidato.rfind(fecha)
            if inicio != -1 and fim > inicio:
                try:
                    return json.loads(candidato[inicio : fim + 1])
                except json.JSONDecodeError:
                    continue

    raise AIResponseParseError(
        f"Nao foi possivel extrair JSON da resposta (inicio: {text[:200]!r})"
    )
