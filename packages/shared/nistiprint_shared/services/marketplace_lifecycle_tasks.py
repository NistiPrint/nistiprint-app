"""Lifecycle effect delivery and historical reconciliation tasks."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_repository import canonical_order_repository
from nistiprint_shared.services.marketplace_lifecycle_service import (
    resolve_mercadolivre,
    resolve_shopee,
)
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)

STATUS_EM_ABERTO = 1
STATUS_EM_ANDAMENTO = 2
BACKFILL_ACTIVE_STATUS_IDS = (
    STATUS_EM_ABERTO,
    STATUS_EM_ANDAMENTO,
)

#: Trava que impede duas cadeias de backfill vivas ao mesmo tempo.
#:
#: A task se auto-encadeia (`continue_batches`) E esta agendada no beat. Sao
#: dois relogios independentes disparando a mesma varredura: quando a cadeia
#: demora mais que o intervalo do beat — e demora, porque cada pedido custa
#: chamadas de detalhe, envio e SLA no marketplace — o beat inicia a proxima
#: antes da anterior terminar, e a partir dai o numero de cadeias vivas so
#: cresce. O sintoma e log repetindo os mesmos `resource_id` intercalados,
#: releitura infinita e quota de API consumida sem nenhum status novo.
#:
#: O TTL e a rede de seguranca: cadeia que morre no meio (worker reiniciado,
#: excecao nao tratada) libera a trava sozinha em vez de travar o backfill para
#: sempre.
BACKFILL_LOCK_KEY = "nistiprint:backfill:marketplace-lifecycle:chain"
BACKFILL_LOCK_TTL_SECONDS = int(
    os.getenv("MARKETPLACE_LIFECYCLE_BACKFILL_LOCK_TTL", "3600")
)


def _adquirir_trava_da_cadeia() -> str | None:
    from nistiprint_shared.services.redis_queue_tasks import get_redis_client

    token = str(uuid.uuid4())
    try:
        adquirida = get_redis_client().set(
            BACKFILL_LOCK_KEY, token, nx=True, ex=BACKFILL_LOCK_TTL_SECONDS
        )
    except Exception as exc:
        # Redis fora do ar nao pode impedir o backfill de rodar; ele so perde a
        # protecao contra sobreposicao, que e o comportamento anterior.
        logger.warning("Backfill sem trava (Redis indisponivel): %s", exc)
        return str(uuid.uuid4())
    return token if adquirida else None


def _renovar_trava_da_cadeia(token: str | None) -> None:
    """Mantem a trava viva enquanto a cadeia avanca de lote."""
    if not token:
        return
    from nistiprint_shared.services.redis_queue_tasks import get_redis_client

    try:
        get_redis_client().eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1,
            BACKFILL_LOCK_KEY,
            token,
            BACKFILL_LOCK_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning("Erro ao renovar trava do backfill: %s", exc)


def _liberar_trava_da_cadeia(token: str | None) -> None:
    if not token:
        return
    from nistiprint_shared.services.redis_queue_tasks import get_redis_client

    try:
        get_redis_client().eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            BACKFILL_LOCK_KEY,
            token,
        )
    except Exception as exc:
        logger.warning("Erro ao liberar trava do backfill: %s", exc)


def process_pending_effects(limit: int = 100) -> dict:
    rows = (
        supabase_db.table("marketplace_order_effects")
        .select("id")
        .eq("status", "pending")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    processed, failed = 0, 0
    for row in rows:
        try:
            supabase_db.rpc(
                "process_marketplace_order_effect",
                {"p_effect_id": row["id"]},
            ).execute()
            processed += 1
        except Exception as exc:
            failed += 1
            logger.exception("Failed marketplace lifecycle effect id=%s", row.get("id"))
            (
                supabase_db.table("marketplace_order_effects")
                .update({
                    "attempt_count": row.get("attempt_count", 0) + 1,
                    "last_error": str(exc)[:4000],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", row["id"])
                .execute()
            )
    return {"status": "success", "processed": processed, "failed": failed}


def _integracoes_do_lote(rows: list[dict]) -> dict:
    """Carrega de uma vez as integracoes citadas no lote.

    Antes era um SELECT por pedido — cem consultas para, no maximo, um punhado
    de contas distintas.
    """
    ids = {row.get("marketplace_integration_id") for row in rows}
    ids.discard(None)
    if not ids:
        return {}
    linhas = (
        supabase_db.table("installed_integrations")
        .select("*")
        .in_("id", list(ids))
        .execute()
        .data
        or []
    )
    return {linha["id"]: linha for linha in linhas}


def _prefetch_detalhes_shopee(rows: list[dict], integracoes: dict, ingest) -> dict:
    """Busca o detalhe dos pedidos Shopee do lote em chamadas de ate 50.

    A API da Shopee aceita 50 `order_sn` por chamada de `get_order_detail`, e a
    varredura pedia um por vez — cem pedidos viravam cem chamadas. Com o
    backfill rodando de hora em hora isso sozinho gerava milhares de chamadas
    diarias e disparou o alerta de anormalidade da Shopee.

    O Mercado Livre fica de fora de proposito: o detalhe la exige tambem envio e
    SLA, que sao endpoints por recurso e nao tem equivalente em lote.
    """
    from nistiprint_shared.services.platform_drivers import shopee as shopee_driver

    por_integracao: dict[int, list[str]] = {}
    for row in rows:
        if row.get("marketplace_module_id") != "shopee":
            continue
        integration_id = row.get("marketplace_integration_id")
        order_id = row.get("marketplace_order_id")
        if not integration_id or not order_id:
            continue
        por_integracao.setdefault(integration_id, []).append(str(order_id))

    detalhes: dict[str, dict] = {}
    for integration_id, order_sns in por_integracao.items():
        integration = integracoes.get(integration_id)
        if not integration:
            continue
        try:
            hidratada = ingest._hydrate_shopee_integration(integration)
            detalhes.update(shopee_driver.get_order_details_batch(hidratada, order_sns))
        except Exception as exc:
            logger.exception(
                "Prefetch Shopee falhou integration_id=%s pedidos=%s",
                integration_id, len(order_sns),
            )
            erro = {"error": str(exc), "error_type": "batch_request_failed"}
            for order_sn in order_sns:
                detalhes.setdefault(order_sn, dict(erro))
    return detalhes


def reconcile_marketplace_lifecycle(
    *,
    dry_run: bool = True,
    days: int = 60,
    limit: int = 100,
    offset: int = 0,
    projection_enabled: bool | None = None,
) -> dict:
    """Backfill de ciclo de vida a partir do estado atual no marketplace.

    `days` limita a varredura por `data_venda`. O parametro existia na
    assinatura e era ignorado no filtro: quem configurava `days: 90` acreditava
    ter delimitado o escopo e varria a base inteira.

    `offset` e keyset, nao deslocamento: o conjunto encolhe conforme os pedidos
    saem de situacao ativa, e paginacao por deslocamento sobre conjunto que muda
    pula justamente as linhas que entraram no lugar das corrigidas. Aqui o valor
    e o ultimo `id` visto, o que torna o lote seguinte independente do que
    aconteceu com os anteriores.
    """
    query = (
        supabase_db.table("pedidos")
        .select("id,numero_pedido,marketplace_module_id,marketplace_order_id,marketplace_integration_id,situacao_pedido_id,erp_order_number,updated_at")
        .in_("marketplace_module_id", ["shopee", "mercadolivre"])
        .in_("situacao_pedido_id", list(BACKFILL_ACTIVE_STATUS_IDS))
    )
    if days and int(days) > 0:
        desde = datetime.now(timezone.utc) - timedelta(days=int(days))
        query = query.gte("data_venda", desde.isoformat())
    if offset:
        query = query.gt("id", int(offset))

    rows = query.order("id").limit(limit).execute().data or []
    from nistiprint_shared.services.marketplace_webhook_ingest_service import (
        MarketplaceWebhookIngestService,
    )

    ingest = MarketplaceWebhookIngestService()
    compared, failed = 0, []
    if dry_run:
        effective_projection_enabled = False
    elif projection_enabled is not None:
        effective_projection_enabled = bool(projection_enabled)
    else:
        effective_projection_enabled = (
            str(os.getenv("MARKETPLACE_LIFECYCLE_PROJECTION_ENABLED", "false")).lower()
            in ("1", "true", "yes", "on")
        )

    integracoes = _integracoes_do_lote(rows)
    detalhes_shopee = _prefetch_detalhes_shopee(rows, integracoes, ingest)

    for row in rows:
        try:
            integration = integracoes.get(row.get("marketplace_integration_id"))
            if not integration:
                raise RuntimeError("marketplace integration not found")
            source = row["marketplace_module_id"]
            order_id = str(row["marketplace_order_id"])
            if source == "shopee":
                detail = detalhes_shopee.get(order_id) or {
                    "error": "detalhe Shopee ausente no lote",
                    "error_type": "provider_resource_not_found",
                }
                lifecycle = resolve_shopee(detail, {"event_type": "backfill"})
            else:
                detail = ingest._fetch_meli_detail(integration, order_id)
                lifecycle = resolve_mercadolivre(detail, {"topic": "backfill"})
            if detail.get("error"):
                raise RuntimeError(detail["error"])
            canonical_order_repository.apply_marketplace_event(
                {
                    "marketplace_module_id": source,
                    "marketplace_order_id": order_id,
                    "marketplace_integration_id": row["marketplace_integration_id"],
                    "ingest_source": source,
                },
                lifecycle_event={
                    **lifecycle.to_event(),
                    "provider_event_id": (
                        f"backfill:{source}:{order_id}:{lifecycle.observed_at or 'current'}"
                    ),
                    "backfill": True,
                    "dry_run": dry_run,
                },
                projection_enabled=effective_projection_enabled,
            )
            if not dry_run and str(row.get("numero_pedido") or "").upper().startswith("SHOPEE-"):
                real_erp_number = str(row.get("erp_order_number") or "").strip()
                if real_erp_number.upper().startswith("SHOPEE-"):
                    real_erp_number = ""
                update = {
                    "numero_pedido": real_erp_number or str(row["id"]),
                }
                if str(row.get("erp_order_number") or "").upper().startswith("SHOPEE-"):
                    update["erp_order_number"] = None
                (
                    supabase_db.table("pedidos")
                    .update(update)
                    .eq("id", row["id"])
                    .execute()
                )
            compared += 1
        except Exception as exc:
            logger.exception("Lifecycle backfill failed pedido_id=%s", row.get("id"))
            failed.append({"pedido_id": row.get("id"), "error": str(exc)})
    return {
        "status": "success",
        "dry_run": dry_run,
        "days": days,
        "compared": compared,
        "failed": failed,
        "next_offset": int(rows[-1]["id"]) if rows else offset,
        "has_more": len(rows) == limit,
        "projection_enabled": effective_projection_enabled,
    }


@shared_task(name="nistiprint_shared.services.marketplace_lifecycle_tasks.process_pending_effects")
@log_task_execution(task_type="PEDIDO", task_name="process_pending_effects")
def process_pending_effects_task(limit: int = 100):
    return process_pending_effects(limit=limit)


@shared_task(name="nistiprint_shared.services.marketplace_lifecycle_tasks.reconcile_marketplace_lifecycle")
@log_task_execution(task_type="PEDIDO", task_name="reconcile_marketplace_lifecycle")
def reconcile_marketplace_lifecycle_task(
    dry_run: bool = True,
    days: int = 60,
    limit: int = 100,
    offset: int = 0,
    projection_enabled: bool | None = None,
    continue_batches: bool = True,
    chain_token: str | None = None,
):
    """Um lote do backfill; se houver mais, encadeia o proximo.

    `chain_token` identifica a cadeia e nao deve ser passado na chamada inicial:
    quem inicia adquire a trava, e os lotes seguintes carregam o token adiante.
    Enquanto uma cadeia estiver viva, um novo disparo do beat vira no-op — ver
    `BACKFILL_LOCK_KEY`.
    """
    inicio_de_cadeia = chain_token is None
    if inicio_de_cadeia:
        chain_token = _adquirir_trava_da_cadeia()
        if chain_token is None:
            logger.info(
                "Backfill de lifecycle ignorado: ja existe uma cadeia em andamento."
            )
            return {"status": "skipped", "reason": "chain_already_running"}

    try:
        result = reconcile_marketplace_lifecycle(
            dry_run=dry_run,
            days=days,
            limit=limit,
            offset=offset,
            projection_enabled=projection_enabled,
        )
    except Exception:
        _liberar_trava_da_cadeia(chain_token)
        raise

    if continue_batches and result.get("has_more"):
        _renovar_trava_da_cadeia(chain_token)
        next_task = reconcile_marketplace_lifecycle_task.apply_async(
            kwargs={
                "dry_run": dry_run,
                "days": days,
                "limit": limit,
                "offset": result["next_offset"],
                "projection_enabled": projection_enabled,
                "continue_batches": True,
                "chain_token": chain_token,
            },
            countdown=10,
        )
        result["next_task_id"] = next_task.id
    else:
        # Fim da cadeia (ou lote unico): a trava sai junto, senao o proximo
        # disparo do beat esperaria o TTL inteiro sem motivo.
        _liberar_trava_da_cadeia(chain_token)

    return result

