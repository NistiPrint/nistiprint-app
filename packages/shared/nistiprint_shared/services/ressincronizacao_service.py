"""Ressincronizacao de pedidos a partir da origem do ingest.

Motivacao: quando a base fica suja ou incoerente (status defasado, pedido que
nunca chegou, enriquecimento parcial), a correcao confiavel nao e mexer no
banco — e reler a verdade na origem e reprocessar pela pipeline normal.

## Principio: nao existe caminho de escrita paralelo

Esta ferramenta NAO escreve em `pedidos`. Ela descobre quais pedidos existem na
origem e devolve cada um para a MESMA pipeline que o webhook usa
(`marketplace_webhook_ingest_service.process`) ou para a mesma rotina de fetch
do Bling (`run_fetch_pedidos_em_andamento`).

    Se a ressincronizacao tivesse upsert proprio, ela divergiria do webhook no
    primeiro campo novo — e a ferramenta que existe para corrigir incoerencia
    viraria fonte de incoerencia.

Consequencia pratica: tudo que o webhook faz (resolucao de marketplace,
espelhos, snapshot canonico, classificacao de modalidade logistica, dedupe)
acontece igual aqui, de graca.

## Duas rotas de origem

Shopee e Mercado Livre tem API propria: lista-se os pedidos pendentes por conta
e sintetiza-se o payload de webhook de cada um.

Demais marketplaces (Amazon, TikTok, Magalu, Kwai, LojaIntegrada...) entram via
Bling. Para esses a origem e o Bling, consultado por `bling_loja_id`, que e o
`shop_id` da loja no marketplace — por isso o vinculo por loja e o que permite
ressincronizar um marketplace especifico sem varrer a conta Bling inteira.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.correlation_service import generate_correlation_id
from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    marketplace_webhook_ingest_service,
)
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver

logger = logging.getLogger(__name__)

#: Status na origem que representam pedido ainda vivo — o que interessa
#: ressincronizar. Concluido/cancelado antigo nao muda mais e so gastaria quota
#: de API.
SHOPEE_STATUS_PENDENTES = [
    "UNPAID",
    "READY_TO_SHIP",
    "PROCESSED",
    "RETRY_SHIP",
    "SHIPPED",
    "TO_CONFIRM_RECEIVE",
]

MELI_STATUS_PENDENTES = ["confirmed", "payment_required", "payment_in_process", "paid"]

#: Codigo de push de pedido da Shopee (marketplace_adapters.ShopeeAdapter).
_SHOPEE_ORDER_CODE = 3


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def listar_contas_marketplace() -> list[dict]:
    """Contas instaladas que podem ser ressincronizadas, com a rota de origem.

    `direta` = tem API propria (Shopee/ML). `bling` = o estado autoritativo vem
    do Bling, consultado pelo shop_id da loja.
    """
    rows = (
        supabase_db.table("installed_integrations")
        .select("id,module_id,instance_name,is_active,is_placeholder,config")
        .eq("is_active", True)
        .execute()
    ).data or []

    contas = []
    for row in rows:
        module_id = (row.get("module_id") or "").strip().lower()
        if module_id == "bling":
            continue
        rota = "direta" if module_id in ("shopee", "mercadolivre") else "bling"
        contas.append({
            "integration_id": row.get("id"),
            "module_id": module_id,
            "nome": row.get("instance_name"),
            "rota": rota,
            "shop_id": (row.get("config") or {}).get("shop_id"),
        })
    contas.sort(key=lambda c: (c["rota"], c["module_id"], c["nome"] or ""))
    return contas


def _integracao(integration_id: int) -> dict | None:
    rows = (
        supabase_db.table("installed_integrations")
        .select("*")
        .eq("id", integration_id)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else None


def _reprocessar_shopee(integracao: dict, dias: int, limite: int | None) -> dict:
    shop_id = (integracao.get("config") or {}).get("shop_id") or (
        integracao.get("credentials") or {}
    ).get("shop_id")

    agora = int(time.time())
    # A Shopee limita a janela de get_order_list a 15 dias por chamada.
    janela = min(int(dias or 7), 15)
    encontrados: list[str] = []

    for status in SHOPEE_STATUS_PENDENTES:
        cursor = ""
        while True:
            filtros = {
                "time_from": agora - (janela * 24 * 3600),
                "time_to": agora,
                "order_status": status,
                "page_size": 100,
            }
            if cursor:
                filtros["cursor"] = cursor

            try:
                pedidos = shopee_driver.get_orders_list(integracao, filtros) or []
            except Exception as exc:
                logger.warning("[ressync] shopee list falhou shop_id=%s status=%s: %s", shop_id, status, exc)
                break

            if pedidos and isinstance(pedidos[0], dict) and pedidos[0].get("error"):
                logger.warning("[ressync] shopee erro shop_id=%s status=%s: %s", shop_id, status, pedidos[0])
                break

            novos = [p.get("external_id") for p in pedidos if p.get("external_id")]
            encontrados.extend(novos)

            if limite and len(encontrados) >= limite:
                break
            # get_orders_list nao expoe o cursor de retorno hoje; sem paginacao
            # confiavel, uma pagina por status evita loop infinito.
            break

        if limite and len(encontrados) >= limite:
            break

    if limite:
        encontrados = encontrados[:limite]

    return _despachar_para_pipeline(
        source="shopee",
        externos=encontrados,
        payload_builder=lambda order_sn: {
            "code": _SHOPEE_ORDER_CODE,
            "shop_id": shop_id,
            "timestamp": agora,
            "data": {"ordersn": order_sn},
        },
    )


def _reprocessar_mercadolivre(integracao: dict, dias: int, limite: int | None) -> dict:
    seller_id = (integracao.get("config") or {}).get("seller_id") or (
        integracao.get("config") or {}
    ).get("user_id")

    desde = _iso(datetime.now(timezone.utc) - timedelta(days=int(dias or 7)))
    encontrados: list[str] = []
    pendentes = set(MELI_STATUS_PENDENTES)

    # /orders/search do ML aceita um unico order_status por chamada e pagina por
    # offset. Filtrar por data e descartar o que ja fechou no cliente sai mais
    # barato do que uma chamada por status.
    offset = 0
    while True:
        try:
            pedidos = meli_driver.get_orders_list(
                integracao,
                {
                    "seller": seller_id,
                    "date_created_from": desde,
                    "limit": 50,
                    "offset": offset,
                },
            ) or []
        except Exception as exc:
            logger.warning("[ressync] meli list falhou seller_id=%s offset=%s: %s", seller_id, offset, exc)
            break

        if pedidos and isinstance(pedidos[0], dict) and pedidos[0].get("error"):
            logger.warning("[ressync] meli erro seller_id=%s: %s", seller_id, pedidos[0])
            break
        if not pedidos:
            break

        for p in pedidos:
            if not isinstance(p, dict):
                continue
            if p.get("status_original") and p["status_original"] not in pendentes:
                continue
            if p.get("external_id"):
                encontrados.append(p["external_id"])

        if limite and len(encontrados) >= limite:
            break
        if len(pedidos) < 50:
            break
        offset += 50
        if offset >= 1000:  # teto de seguranca contra varredura infinita
            break

    if limite:
        encontrados = encontrados[:limite]

    return _despachar_para_pipeline(
        source="mercadolivre",
        externos=encontrados,
        payload_builder=lambda order_id: {
            "topic": "orders_v2",
            "resource": f"/orders/{order_id}",
            "user_id": seller_id,
        },
    )


def _despachar_para_pipeline(*, source: str, externos: list[str], payload_builder) -> dict:
    """Devolve cada pedido para a pipeline de ingest normal, um a um.

    Falha de um pedido nunca interrompe o lote: ressincronizacao parcial e
    melhor que nenhuma, e o pedido que falhou aparece em `erros` para
    investigacao.
    """
    correlation_id = generate_correlation_id()
    processados = 0
    erros: list[dict] = []

    for externo in externos:
        try:
            resultado = marketplace_webhook_ingest_service.process(
                source,
                payload_builder(externo),
                correlation_id=correlation_id,
            )
            if resultado.get("status") in ("error", "failed"):
                erros.append({"externo": externo, "erro": resultado.get("message")})
            else:
                processados += 1
        except Exception as exc:
            erros.append({"externo": externo, "erro": str(exc)})

    return {
        "listados": len(externos),
        "processados": processados,
        "erros": erros[:20],
        "total_erros": len(erros),
        "correlation_id": correlation_id,
    }


def ressincronizar_conta(
    integration_id: int,
    *,
    dias: int = 7,
    limite: int | None = None,
) -> dict:
    """Rele os pedidos pendentes de UMA conta na origem e reprocessa."""
    integracao = _integracao(integration_id)
    if not integracao:
        return {"status": "ERRO", "message": f"Integração {integration_id} não encontrada."}

    module_id = (integracao.get("module_id") or "").strip().lower()
    nome = integracao.get("instance_name")

    if module_id == "shopee":
        resultado = _reprocessar_shopee(integracao, dias, limite)
    elif module_id == "mercadolivre":
        resultado = _reprocessar_mercadolivre(integracao, dias, limite)
    else:
        # Marketplace sem API propria: a origem autoritativa e o Bling, pelo
        # vinculo de loja. Delegado a rotina que ja existe.
        from nistiprint_shared.services.pedidos_bling_import_service import (
            run_fetch_pedidos_em_andamento,
        )

        stats = run_fetch_pedidos_em_andamento(
            dias=dias,
            only_plataformas=[module_id],
            limit_pedidos=limite,
        )
        totals = (stats or {}).get("totals") or {}
        return {
            "status": "OK",
            "integration_id": integration_id,
            "module_id": module_id,
            "nome": nome,
            "rota": "bling",
            "listados": totals.get("orders_listed", 0),
            "processados": totals.get("orders_synced", 0),
            "total_erros": totals.get("errors", 0),
            "erros": [],
            "detalhe_bling": stats,
        }

    return {
        "status": "OK",
        "integration_id": integration_id,
        "module_id": module_id,
        "nome": nome,
        "rota": "direta",
        **resultado,
    }
