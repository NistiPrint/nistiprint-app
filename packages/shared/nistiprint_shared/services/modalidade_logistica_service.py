"""Classificacao de modalidade logistica no ingest.

Contrato: docs/specs/02-domains/despacho/spec.md e data-model.md

Mesma arquitetura de `logistics_canonicalization.py`: um registro de extratores
por `module_id` devolve fatos crus (chave estavel + rotulo de exibicao); a
classificacao em si mora no banco (`classificar_pedido_modalidade`), porque o
catalogo de modalidades e regras e dado de cadastro, nao codigo Python. Se
amanha o admin cadastra "Shopee Turbo Noturno" com uma regra nova, este arquivo
Python nao muda uma linha.

    Se aparecer um `if modalidade == 'TURBO'` fora de um extrator, a regra esta
    no lugar errado — modalidade e cadastro, nao enum de codigo.

## Chave versus rotulo

A Shopee expoe as duas coisas com papeis diferentes em `get_order_detail`:

    logistics_channel_id   90011, 90012        identificador estavel
    shipping_carrier        "Entrega Turbo"     rotulo de exibicao

Extratores devolvem sempre os dois. Classificar por rotulo e fragil (string de
marketing muda por renomeacao); o rotulo serve para o alerta de metodo novo ser
legivel, nao para a regra em si.

## Falha aberta, nunca bloqueante

Se a extracao nao encontrar nada, ou a chamada ao banco falhar, o pedido segue
sem modalidade classificada. Ele continua listavel e lancavel — cai no no
"Modalidade nao classificada" da arvore de despacho, com prioridade maxima,
porque prazo desconhecido e a hipotese mais perigosa. Nunca se levanta excecao
que interrompa o ingest por causa de classificacao de modalidade.
"""
from __future__ import annotations

import logging
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger(__name__)


def _extract_shopee(detail: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
    detail = detail or {}
    raw = detail.get("raw") or {}
    chave = (
        detail.get("logistics_channel_id")
        or raw.get("logistics_channel_id")
    )
    rotulo = detail.get("shipping_carrier") or raw.get("shipping_carrier")
    return (
        str(chave) if chave not in (None, "") else None,
        str(rotulo) if rotulo not in (None, "") else None,
        "logistics_channel_id",
    )


def _extract_mercadolivre(detail: dict[str, Any] | None) -> tuple[str | None, str | None, str]:
    # GAP (data-model.md, Riscos): posicao do metodo de envio no payload ML
    # ainda nao inspecionada em producao. shipment.logistic.type e o candidato
    # mais proximo de um identificador estavel (me2, me1, self_service),
    # tratado hoje so como sinal textual em logistics_canonicalization.
    detail = detail or {}
    shipment = detail.get("shipment") or {}
    logistic = shipment.get("logistic") or {}
    chave = logistic.get("type") or shipment.get("logistic_type")
    rotulo = (shipment.get("shipping_option") or {}).get("name") if isinstance(
        shipment.get("shipping_option"), dict
    ) else shipment.get("mode")
    return (
        str(chave) if chave not in (None, "") else None,
        str(rotulo) if rotulo not in (None, "") else None,
        "logistic.type",
    )


#: Registro de extratores por module_id. Adicionar uma plataforma nova e
#: adicionar uma entrada aqui — nunca um `if` dentro da funcao de classificacao.
_EXTRACTORS = {
    "shopee": _extract_shopee,
    "mercadolivre": _extract_mercadolivre,
}


def extract_metodo_envio(module_id: str | None, detail: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    """Devolve (chave, rotulo, campo_origem) crus, sem tocar banco."""
    extractor = _EXTRACTORS.get(str(module_id or "").strip().lower())
    if not extractor:
        return None, None, None
    try:
        return extractor(detail)
    except Exception:
        logger.warning("[modalidade] falha ao extrair metodo de envio module_id=%s", module_id, exc_info=True)
        return None, None, None


def classify_pedido(
    *,
    pedido_id: int | None,
    module_id: str | None,
    integration_id: int | None,
    detail: dict[str, Any] | None,
) -> None:
    """Extrai, registra e classifica. Nunca levanta excecao para o chamador.

    Efeitos:
      1. `pedidos.metodo_envio_chave` / `metodo_envio_rotulo` atualizados.
      2. `metodos_envio_observados` incrementado (deteccao de metodo novo).
      3. `pedidos.modalidade_logistica_id` / `compromisso_logistico_em`
         resolvidos via `classificar_pedido_modalidade` no banco.

    Chamar depois que o pedido ja existe em `pedidos` (precisa de pedido_id).
    """
    if not pedido_id:
        return

    chave, rotulo, campo_origem = extract_metodo_envio(module_id, detail)
    if not chave:
        return

    try:
        supabase_db.table("pedidos").update({
            "metodo_envio_chave": chave,
            "metodo_envio_rotulo": rotulo,
        }).eq("id", pedido_id).execute()
    except Exception:
        logger.warning(
            "[modalidade] falha ao gravar metodo_envio pedido_id=%s module_id=%s",
            pedido_id, module_id, exc_info=True,
        )
        return

    try:
        supabase_db.rpc("registrar_metodo_envio_observado", {
            "p_module_id": module_id,
            "p_integration_id": integration_id,
            "p_campo_origem": campo_origem,
            "p_chave": chave,
            "p_rotulo": rotulo,
            "p_pedido_id": pedido_id,
        }).execute()
    except Exception:
        # Deteccao de metodo novo e observabilidade, nao caminho critico.
        # Uma falha aqui nao pode impedir a classificacao em si.
        logger.warning(
            "[modalidade] falha ao registrar metodo observado pedido_id=%s chave=%s",
            pedido_id, chave, exc_info=True,
        )

    try:
        result = supabase_db.rpc("classificar_pedido_modalidade", {
            "p_pedido_id": pedido_id,
        }).execute()
        modalidade_id = (result.data if not isinstance(result.data, list) else
                          (result.data[0] if result.data else None))
        logger.info(
            "[modalidade] pedido_id=%s module_id=%s chave=%s -> modalidade_id=%s",
            pedido_id, module_id, chave, modalidade_id,
        )
    except Exception:
        logger.warning(
            "[modalidade] falha ao classificar pedido_id=%s chave=%s",
            pedido_id, chave, exc_info=True,
        )

