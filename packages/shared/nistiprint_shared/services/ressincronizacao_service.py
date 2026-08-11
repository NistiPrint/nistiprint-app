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

Na rota inversa (`ressincronizar_pendentes`) o Bling e consultado pedido a
pedido, por `erp_order_id`, e nao por loja/periodo: partindo da nossa base ja
sabemos exatamente qual pedido esta defasado, e uma leitura por id custa uma
chamada em vez de varrer a loja inteira.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling_client_resolver_service import (
    bling_client_resolver_service,
)
from nistiprint_shared.services.correlation_service import generate_correlation_id
from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    marketplace_webhook_ingest_service,
)
from nistiprint_shared.services.platform_drivers import mercadolivre as meli_driver
from nistiprint_shared.services.platform_drivers import shopee as shopee_driver
from nistiprint_shared.utils.task_logging import log_task_execution

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

#: Situacoes internas que ainda podem mudar. Cancelado (7), Entregue (6) e
#: Devolvido (8) sao finais e reprocessa-las so gastaria quota de API.
SITUACOES_NAO_FINALIZADAS = [1, 2, 3, 4, 5]

#: Origens com API propria: da para reler pedido a pedido direto no marketplace.
#: As demais sao lidas no Bling, que e quem mantem a integracao com elas.
ORIGENS_COM_API_PROPRIA = {"mercadolivre": "mercadolivre", "shopee": "shopee"}

#: Chave em `configuracoes_aplicacao` onde a varredura periodica guarda ate onde
#: chegou. Sem isso a task reprocessa eternamente a mesma janela — ver
#: `_pedidos_nao_finalizados`.
CURSOR_CONFIG_KEY = "ressync_pendentes_cursor"


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


# ---------------------------------------------------------------------------
# Rota inversa: parte dos pedidos travados na NOSSA base
# ---------------------------------------------------------------------------
#
# `ressincronizar_conta` pergunta a origem "o que existe?" e filtra por data de
# criacao. Isso deixa escapar exatamente o caso que mais dói: o pedido que
# ficou defasado ha semanas, fora da janela de dias.
#
# `ressincronizar_pendentes` inverte a pergunta: parte de cada pedido que ainda
# esta numa situacao nao-final aqui e vai reler a verdade na origem. A garantia
# de consistencia e a mesma — nada e escrito direto em `pedidos`, tudo volta
# pela pipeline do webhook.


def _pedidos_nao_finalizados(
    *,
    origens: list[str] | None,
    situacoes: list[int] | None,
    limite: int,
    depois_do_id: int | None = None,
    pedido_ids: list[int] | None = None,
) -> list[dict]:
    """Lote de pedidos ainda em situacao nao-final.

    Ordena por `id` — e nao por `data_venda` — de proposito. Ordenar pelos mais
    antigos parece certo e e a armadilha: a janela so anda quando o pedido mais
    antigo sai da situacao nao-final, e pedido velho travado por definicao nao
    sai. Na pratica a varredura reprocessava sempre o mesmo topo da lista e
    nunca chegava no resto da base.

    Com `depois_do_id` a leitura vira keyset: cada execucao continua de onde a
    anterior parou e a base inteira e coberta em algumas rodadas.
    """
    query = (
        supabase_db.table("pedidos")
        .select(
            "id,marketplace_order_id,origem,situacao_pedido_id,"
            "marketplace_integration_id,data_venda,"
            "erp_order_id,erp_order_number,erp_integration_id"
        )
        .in_("situacao_pedido_id", situacoes or SITUACOES_NAO_FINALIZADAS)
    )
    if origens:
        query = query.in_("origem", [o.strip().upper() for o in origens])
    if pedido_ids:
        query = query.in_("id", [int(i) for i in pedido_ids])
    if depois_do_id:
        query = query.gt("id", int(depois_do_id))

    return (
        query.order("id", desc=False)
        .limit(max(1, min(int(limite), 2000)))
        .execute()
        .data
        or []
    )


def _ler_cursor() -> int:
    # Import tardio de proposito: `app_config_service` resolve a tabela no
    # import e derruba quem apenas importa este modulo sem Supabase configurado.
    from nistiprint_shared.services.app_config_service import app_config_service

    try:
        return int(app_config_service.get_config(CURSOR_CONFIG_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def _gravar_cursor(valor: int) -> None:
    """Persiste o avanco da varredura.

    Falha de cursor nao pode derrubar a ressincronizacao: no pior caso a proxima
    execucao repete o lote, o que e inofensivo porque todo o processamento e
    idempotente.
    """
    from nistiprint_shared.services.app_config_service import app_config_service

    try:
        app_config_service.set_config(CURSOR_CONFIG_KEY, int(valor))
    except Exception as exc:
        logger.warning("[ressync-pendentes] falha ao gravar cursor=%s: %s", valor, exc)


def _integracoes_por_id(ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    rows = (
        supabase_db.table("installed_integrations")
        .select("id,module_id,instance_name,config")
        .in_("id", list(ids))
        .execute()
        .data
        or []
    )
    return {row["id"]: row for row in rows}


def _payload_reingest(origem: str, pedido: dict, integracao: dict) -> dict | None:
    """Sintetiza o payload de webhook que a pipeline ja sabe processar."""
    externo = pedido.get("marketplace_order_id")
    if not externo:
        return None
    config = integracao.get("config") or {}

    if origem == "mercadolivre":
        seller_id = config.get("seller_id") or config.get("user_id")
        return {
            "topic": "orders_v2",
            "resource": f"/orders/{externo}",
            "user_id": seller_id,
        }
    if origem == "shopee":
        return {
            "code": _SHOPEE_ORDER_CODE,
            "shop_id": config.get("shop_id"),
            "timestamp": int(time.time()),
            "data": {"ordersn": externo},
        }
    return None


def _reler_no_bling(pedido: dict, correlation_id: str) -> dict:
    """Rele um pedido na API do Bling e devolve para a pipeline do webhook.

    Amazon, Magalu, TikTok e afins nao tem API propria aqui, mas o Bling e
    integrado com eles: o status desses pedidos evolui la. Tratar essas origens
    como "sem rota" era desistir de informacao que existe — e justamente nas
    origens em que o webhook e o unico canal, portanto as que mais sofrem quando
    uma notificacao se perde.

    A leitura e por `erp_order_id` (o id do pedido no Bling), nao por loja e
    periodo: partindo da nossa base ja sabemos qual pedido esta defasado.

    Como em toda esta ferramenta, nada e escrito direto em `pedidos`: o detalhe
    lido vai para `process_webhook`, a mesma funcao que o worker de ingest chama
    ao consumir um webhook do Bling.
    """
    from nistiprint_shared.services.bling_order_processing_service import process_webhook

    erp_order_id = pedido.get("erp_order_id")
    if not erp_order_id:
        raise ValueError("pedido sem erp_order_id para leitura no Bling")

    cliente = bling_client_resolver_service.resolve_client(
        bling_integration_id=pedido.get("erp_integration_id"),
        marketplace_integration_id=pedido.get("marketplace_integration_id"),
        platform_name=(pedido.get("origem") or "").strip().lower() or None,
        function_name="ORDER_IMPORT",
    )[0]

    detalhe = cliente.get_order(erp_order_id)
    if not detalhe:
        raise RuntimeError(f"pedido {erp_order_id} nao encontrado no Bling")

    return process_webhook(
        detalhe,
        bling_integration_hint=pedido.get("erp_integration_id"),
        correlation_id=correlation_id,
    )


def ressincronizar_pendentes(
    *,
    origens: list[str] | None = None,
    situacoes: list[int] | None = None,
    limite: int = 200,
    dry_run: bool = False,
    pausa_segundos: float = 0.0,
    usar_cursor: bool = False,
    pedido_ids: list[int] | None = None,
) -> dict:
    """Rele na origem todo pedido que ainda esta numa situacao nao-final.

    origens: filtra por `pedidos.origem` (ex.: ["MERCADOLIVRE"]). None = todas.
    situacoes: ids de `situacoes_pedido`. None = todas as nao-finais.
    limite: teto de pedidos por execucao, para nao estourar quota de API.
    dry_run: apenas conta e agrupa, sem chamar a origem.
    usar_cursor: continua de onde a execucao anterior parou e da a volta ao
        chegar no fim. E o modo da varredura periodica. O disparo manual usa
        False para operar exatamente sobre o filtro que o operador pediu.
    pedido_ids: restringe a um conjunto especifico. Existe para o caso que
        motivou esta ferramenta — o operador identifica os pedidos defasados por
        consulta e quer desafogar exatamente aqueles, sem varrer a base inteira
        e gastar quota de API com pedidos que estao em dia.

    Cada pedido segue por uma de duas rotas, nunca por escrita direta em
    `pedidos`: marketplace com API propria (Shopee/ML) volta pela pipeline do
    webhook do marketplace; os demais sao relidos no Bling por `erp_order_id` e
    voltam pela pipeline do webhook do Bling.
    """
    cursor_inicial = _ler_cursor() if usar_cursor else 0
    pedidos = _pedidos_nao_finalizados(
        origens=origens,
        situacoes=situacoes,
        limite=limite,
        depois_do_id=cursor_inicial or None,
        pedido_ids=pedido_ids,
    )

    # Fim da base: da a volta na hora, em vez de gastar a execucao a toa.
    if usar_cursor and not pedidos and cursor_inicial:
        pedidos = _pedidos_nao_finalizados(
            origens=origens,
            situacoes=situacoes,
            limite=limite,
            pedido_ids=pedido_ids,
        )

    if not pedidos:
        if usar_cursor:
            _gravar_cursor(0)
        return {
            "status": "OK",
            "listados": 0,
            "processados": 0,
            "total_erros": 0,
            "erros": [],
            "por_origem": {},
            "por_rota": {},
            "cursor_inicial": cursor_inicial,
            "cursor_final": 0,
        }

    por_origem: dict[str, int] = {}
    for pedido in pedidos:
        chave = (pedido.get("origem") or "DESCONHECIDA").upper()
        por_origem[chave] = por_origem.get(chave, 0) + 1

    # Lote menor que o teto significa que a base acabou: a proxima execucao
    # recomeca do inicio em vez de ficar presa na cauda.
    cursor_final = 0 if len(pedidos) < limite else int(pedidos[-1]["id"])

    if dry_run:
        return {
            "status": "OK",
            "dry_run": True,
            "listados": len(pedidos),
            "processados": 0,
            "total_erros": 0,
            "erros": [],
            "por_origem": por_origem,
            "por_rota": {},
            "cursor_inicial": cursor_inicial,
            "cursor_final": cursor_inicial,
        }

    integracoes = _integracoes_por_id({
        pedido["marketplace_integration_id"]
        for pedido in pedidos
        if pedido.get("marketplace_integration_id")
    })

    correlation_id = generate_correlation_id()
    processados = 0
    erros: list[dict] = []
    por_rota: dict[str, int] = {"direta": 0, "bling": 0}

    for pedido in pedidos:
        origem = (pedido.get("origem") or "").strip().lower()
        source = ORIGENS_COM_API_PROPRIA.get(origem)
        integracao = integracoes.get(pedido.get("marketplace_integration_id"))
        rota = "direta" if (source and integracao) else "bling"

        try:
            if rota == "direta":
                payload = _payload_reingest(source, pedido, integracao)
                if not payload:
                    raise ValueError("pedido sem identificador do marketplace")
                resultado = marketplace_webhook_ingest_service.process(
                    source, payload, correlation_id=correlation_id
                )
            else:
                resultado = _reler_no_bling(pedido, correlation_id)

            if (resultado or {}).get("status") in ("error", "failed"):
                erros.append({
                    "pedido_id": pedido.get("id"),
                    "externo": pedido.get("marketplace_order_id"),
                    "rota": rota,
                    "erro": (resultado or {}).get("message")
                    or (resultado or {}).get("reason"),
                })
            else:
                processados += 1
                por_rota[rota] += 1
        except Exception as exc:
            erros.append({
                "pedido_id": pedido.get("id"),
                "externo": pedido.get("marketplace_order_id"),
                "rota": rota,
                "erro": str(exc),
            })

        if pausa_segundos > 0:
            time.sleep(pausa_segundos)

    if usar_cursor:
        _gravar_cursor(cursor_final)

    return {
        "status": "OK",
        "listados": len(pedidos),
        "processados": processados,
        "erros": erros[:20],
        "total_erros": len(erros),
        "por_origem": por_origem,
        "por_rota": por_rota,
        "cursor_inicial": cursor_inicial,
        "cursor_final": cursor_final if usar_cursor else cursor_inicial,
        "correlation_id": correlation_id,
    }


@shared_task(
    name="nistiprint_shared.services.ressincronizacao_service.ressincronizar_pendentes"
)
@log_task_execution(task_type="PEDIDO", task_name="ressincronizar_pendentes")
def ressincronizar_pendentes_task(
    origens: list[str] | None = None,
    situacoes: list[int] | None = None,
    limite: int = 200,
    dry_run: bool = False,
    pausa_segundos: float = 0.2,
    usar_cursor: bool = True,
):
    """Varredura periodica dos pedidos nao-finalizados.

    O default tem pausa entre chamadas porque, ao contrario do disparo manual,
    esta task compete com o trafego normal de webhooks pela quota de API.

    `usar_cursor=True` por padrao: a varredura periodica so cumpre o proposito
    se percorrer a base inteira ao longo das execucoes. Sem cursor ela reprocessa
    a mesma janela para sempre e os pedidos fora dela nunca sao verificados.

    O `@log_task_execution` nao e decorativo. Esta task ficou habilitada em
    `configuracoes_aplicacao` sem nunca ter rodado — o beat le o schedule no
    start e nao havia sido reiniciado — e a ausencia foi indistinguivel de
    sucesso porque nada era registrado.
    """
    resultado = ressincronizar_pendentes(
        origens=origens,
        situacoes=situacoes,
        limite=limite,
        dry_run=dry_run,
        pausa_segundos=pausa_segundos,
        usar_cursor=usar_cursor,
    )
    logger.info(
        "[ressync-pendentes] listados=%s processados=%s erros=%s "
        "por_origem=%s por_rota=%s cursor=%s->%s",
        resultado.get("listados"),
        resultado.get("processados"),
        resultado.get("total_erros"),
        resultado.get("por_origem"),
        resultado.get("por_rota"),
        resultado.get("cursor_inicial"),
        resultado.get("cursor_final"),
    )
    return resultado
