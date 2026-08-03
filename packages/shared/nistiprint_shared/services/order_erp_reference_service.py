from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_repository import canonical_order_repository
from nistiprint_shared.services.integration_capability_service import INVOICING, integration_capability_service
from nistiprint_shared.utils.date_utils import get_now_iso
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)


def _ml_pack_ids_por_pedido(order_ids: list) -> dict:
    """Mapa marketplace_order_id -> pack_id para pedidos Mercado Livre.

    Um pedido ML enviado junto com outro(s) do mesmo comprador (pack) as vezes
    e importado no Bling sob o pack_id, nao o id do pedido individual —
    "Numero da Loja" no Bling vem preenchido com o pack mesmo quando o pedido
    interno tem um so item. Sem tentar o pack_id como alternativa, esses
    pedidos nunca reconciliam. Visto em 03/08: pedido 54449, numeroLoja real
    2000014317620711 != marketplace_order_id 2000017713411420 (o pack_id
    esta em pedidos_mercadolivre.raw_order->>'pack_id').
    """
    if not order_ids:
        return {}
    rows = (
        supabase_db.table("pedidos_mercadolivre")
        .select("codigo_pedido,raw_order")
        .in_("codigo_pedido", [str(o) for o in order_ids])
        .execute()
        .data
        or []
    )
    pacotes = {}
    for row in rows:
        order_id = str(row.get("codigo_pedido") or "").strip()
        pack_id = str((row.get("raw_order") or {}).get("pack_id") or "").strip()
        if order_id and pack_id and pack_id != order_id:
            pacotes[order_id] = pack_id
    return pacotes


class OrderErpReferenceService:
    """Resolves Bling references without making ERP a prerequisite for ingest."""

    READY_FIELDS = "erp_integration_id,erp_store_id,erp_order_id,erp_order_number"

    def resolve_order(self, pedido_id: int, *, allow_remote: bool = True) -> dict[str, Any]:
        if not pedido_id:
            return {"status": "missing_identity", "pedido_id": pedido_id, "message": "Pedido sem id interno"}
        rows = (
            supabase_db.table("pedidos")
            .select(
                "id,marketplace_module_id,marketplace_order_id,marketplace_integration_id,"
                "erp_integration_id,erp_store_id,erp_order_id,erp_order_number"
            )
            .eq("id", pedido_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return {"status": "not_found", "pedido_id": pedido_id, "message": "Pedido nao encontrado"}

        pedido = dict(rows[0])
        ready = self._ready_reference(pedido)
        if ready:
            return {"status": "ready", "pedido_id": pedido_id, **ready}
        if not allow_remote:
            return {"status": "pending", "pedido_id": pedido_id, "message": "Referencia ERP ainda nao disponivel"}

        marketplace_integration_id = pedido.get("marketplace_integration_id")
        if not marketplace_integration_id:
            return {"status": "missing_link", "pedido_id": pedido_id, "message": "Pedido sem instancia de marketplace"}

        resolved = integration_capability_service.resolve(
            marketplace_integration_id,
            INVOICING,
            context={
                "erp_store_id": pedido.get("erp_store_id"),
                "external_order_id": pedido.get("marketplace_order_id"),
            },
        )
        if resolved.reason == "ambiguous_erp_link":
            return {"status": "ambiguous", "pedido_id": pedido_id, "message": "Mais de uma conta ERP atende este pedido"}
        if not resolved.responsible_integration:
            return {"status": "missing_link", "pedido_id": pedido_id, "message": "Nenhuma conta ERP vinculada ao marketplace"}

        from nistiprint_shared.services.bling.bling_client import BlingClient

        erp_integration_id = int(resolved.integration_id)
        link = resolved.link or {}
        erp_store_id = link.get("erp_store_id") or link.get("aggregator_store_id")
        external_order_id = str(pedido.get("marketplace_order_id") or "").strip()
        if not external_order_id:
            return {"status": "missing_identity", "pedido_id": pedido_id, "message": "Pedido sem identidade externa"}

        pack_id = None
        if pedido.get("marketplace_module_id") == "mercadolivre":
            pack_id = _ml_pack_ids_por_pedido([external_order_id]).get(external_order_id)
        candidatos = [external_order_id] + ([pack_id] if pack_id else [])

        try:
            client = BlingClient.create_client_for_integration_id(erp_integration_id)
            matches = client.get_order_numbers_by_store_numbers(candidatos) or []
        except Exception as exc:
            logger.warning("Falha ao resolver ERP do pedido %s: %s", pedido_id, exc, exc_info=True)
            return {"status": "error", "pedido_id": pedido_id, "message": str(exc)}

        por_numero: dict[str, list] = {}
        for row in matches:
            numero_loja = str(row.get("numeroLoja") or "").strip()
            if numero_loja in candidatos and row.get("id") and row.get("numero"):
                por_numero.setdefault(numero_loja, []).append(row)

        # Prioriza o match pelo id do pedido; so cai pro pack_id se o Bling nao
        # tiver registrado o pedido individualmente.
        exact = por_numero.get(external_order_id) or (por_numero.get(pack_id) if pack_id else None) or []
        if not exact:
            return {"status": "pending", "pedido_id": pedido_id, "message": "Pedido ainda nao encontrado no ERP"}
        if len(exact) > 1:
            return {"status": "ambiguous", "pedido_id": pedido_id, "message": "Pedido encontrado mais de uma vez no ERP"}

        match = exact[0]
        canonical_order_repository.upsert(
            {
                "marketplace_module_id": pedido.get("marketplace_module_id"),
                "marketplace_order_id": external_order_id,
                "marketplace_integration_id": marketplace_integration_id,
                "erp_integration_id": erp_integration_id,
                "erp_store_id": str(erp_store_id) if erp_store_id not in (None, "") else None,
                "erp_order_id": match.get("id"),
                "erp_order_number": str(match.get("numero")),
            },
            refs=[{
                "integration_id": erp_integration_id,
                "module_id": "bling",
                "role": "erp",
                "external_order_id": str(match.get("id")),
                "metadata": {"store_id": erp_store_id},
            }],
        )
        (
            supabase_db.table("pending_order_reconciliations")
            .update({"status": "applied", "resolved_at": get_now_iso(), "last_error": None})
            .eq("pedido_id", pedido_id)
            .eq("status", "pending")
            .execute()
        )
        return {
            "status": "ready", "pedido_id": pedido_id,
            "erp_integration_id": erp_integration_id, "erp_store_id": erp_store_id,
            "erp_order_id": match.get("id"), "erp_order_number": str(match.get("numero")),
        }

    def resolve_many(self, pedido_ids: list[int], *, allow_remote: bool = True) -> dict[str, list[dict]]:
        results = [self.resolve_order(int(pedido_id), allow_remote=allow_remote) for pedido_id in pedido_ids]
        return {
            "ready": [result for result in results if result.get("status") == "ready"],
            "blocked": [result for result in results if result.get("status") != "ready"],
        }

    @staticmethod
    def _ready_reference(pedido: dict) -> dict | None:
        integration_id = pedido.get("erp_integration_id")
        order_id = pedido.get("erp_order_id")
        order_number = pedido.get("erp_order_number")
        if not integration_id or not order_id or not order_number:
            return None
        return {
            "erp_integration_id": int(integration_id),
            "erp_store_id": pedido.get("erp_store_id"),
            "erp_order_id": order_id,
            "erp_order_number": str(order_number),
        }



def _resolve_pending_references_in_batch(rows: list[dict]) -> dict:
    """Consulta numeroLoja agrupando pedidos pela mesma conta Bling."""
    from nistiprint_shared.services.bling.bling_client import BlingClient
    grouped = {}
    results = []
    pedidos_por_id = {}
    for row in rows:
        pedido = (supabase_db.table("pedidos")
            .select("id,marketplace_order_id,marketplace_integration_id,marketplace_module_id,erp_store_id,pack_id,erp_order_id")
            .eq("id", row.get("pedido_id")).limit(1).execute().data or [])
        if not pedido:
            results.append({"status": "not_found", "pedido_id": row.get("pedido_id")})
            continue
        pedido = pedido[0]
        # Irmao de pacote ja resolvido: `enrich_order_erp_reference` aplica a
        # referencia no pacote inteiro de uma vez, entao o irmao chega aqui
        # pronto. Gastar uma consulta ao Bling para redescobrir o que ele ja tem
        # so serviria para ele reivindicar de novo o mesmo pedido do ERP.
        if pedido.get("erp_order_id"):
            results.append({"status": "ready", "pedido_id": pedido["id"]})
            continue
        pedidos_por_id[pedido["id"]] = pedido
        resolved = integration_capability_service.resolve(
            pedido.get("marketplace_integration_id"), INVOICING,
            context={"erp_store_id": pedido.get("erp_store_id"),
                     "external_order_id": pedido.get("marketplace_order_id")})
        if not resolved.responsible_integration or resolved.reason == "ambiguous_erp_link":
            results.append({"status": "missing_link", "pedido_id": pedido["id"]})
            continue
        link = resolved.link or {}
        key = (int(resolved.integration_id), str(link.get("erp_store_id") or link.get("aggregator_store_id") or ""))
        grouped.setdefault(key, []).append(pedido)

    # Pedido ML dentro de um pack pode estar no Bling sob o pack_id, nao o id
    # do pedido individual. Ver _ml_pack_ids_por_pedido.
    ml_order_ids = [
        p["marketplace_order_id"] for p in pedidos_por_id.values()
        if p.get("marketplace_module_id") == "mercadolivre" and p.get("marketplace_order_id")
    ]
    pack_ids = _ml_pack_ids_por_pedido(ml_order_ids)

    for (integration_id, store_id), pedidos in grouped.items():
        ids = set()
        for p in pedidos:
            order_id = p.get("marketplace_order_id")
            if not order_id:
                continue
            ids.add(str(order_id))
            pack_id = pack_ids.get(str(order_id))
            if pack_id:
                ids.add(pack_id)
        try:
            matches = BlingClient.create_client_for_integration_id(integration_id).get_order_numbers_by_store_numbers(list(ids)) or []
        except Exception as exc:
            logger.warning("Falha no lote de referencias Bling: %s", exc, exc_info=True)
            results.extend({"status": "error", "pedido_id": p["id"], "message": str(exc)} for p in pedidos)
            continue
        by_store = {str(m.get("numeroLoja")): m for m in matches if m.get("numeroLoja") and m.get("id") and m.get("numero")}
        for pedido in pedidos:
            order_id = str(pedido.get("marketplace_order_id") or "")
            match = by_store.get(order_id) or by_store.get(pack_ids.get(order_id, ""))
            if not match:
                results.append({"status": "pending", "pedido_id": pedido["id"], "message": "Pedido ainda nao encontrado no ERP"})
                continue
            # Isolado por pedido de proposito. Antes, uma excecao aqui abortava o
            # lote inteiro e derrubava a task: um pedido problematico impedia a
            # reconciliacao de todos os outros da rodada. O caso real foi um
            # pacote ML, mas a fragilidade era estrutural — qualquer erro do
            # banco tinha o mesmo alcance.
            try:
                supabase_db.rpc("enrich_order_erp_reference", {
                    "p_pedido_id": pedido["id"], "p_erp_integration_id": integration_id,
                    "p_erp_store_id": store_id or None, "p_erp_order_id": match["id"],
                    "p_erp_order_number": str(match["numero"]),
                    "p_marketplace_order_id": pedido.get("marketplace_order_id"),
                }).execute()
            except Exception as exc:
                logger.warning(
                    "Falha ao aplicar referencia ERP no pedido %s (bling_id=%s): %s",
                    pedido["id"], match.get("id"), exc, exc_info=True,
                )
                results.append({"status": "error", "pedido_id": pedido["id"], "message": str(exc)})
                continue
            results.append({"status": "ready", "pedido_id": pedido["id"]})
    return {"ready": [r for r in results if r["status"] == "ready"],
            "blocked": [r for r in results if r["status"] != "ready"]}

order_erp_reference_service = OrderErpReferenceService()


#: Situacoes em que o pedido nunca mais vai ganhar referencia de ERP.
#:
#: O Bling so importa pedido que se concretizou. Um pedido cancelado ou
#: devolvido no marketplace normalmente nunca chega la — e nem precisa: ele nao
#: sera faturado nem impresso. Medido em 02/08: dos 128 itens que esgotaram as
#: 20 tentativas, 64 eram devolucoes. Metade do trabalho da fila era perseguir
#: pedidos que, por definicao, nunca iam aparecer.
TERMINAL_SITUACAO_IDS = (7, 8)  # 7 Cancelado, 8 Devolvido

#: Espera antes da proxima consulta ao Bling, por numero de tentativas ja feitas.
#:
#: Calibrado com dados reais de 02/08/2026 (apenas itens posteriores ao restart
#: do beat; antes disso a fila estava represada e a media era artefato):
#:
#:     n=22  menor=1min  mediana=49min  p90=90min  maior=97min
#:
#: A politica anterior — 20 tentativas a cada 60s — desistia em ~20 minutos,
#: menos da metade da mediana. Os 64 itens em `failed` nao eram pedidos ausentes
#: do Bling; eram pedidos que ainda nao tinham chegado quando paramos de
#: perguntar.
#:
#: O formato da curva justifica o backoff: quase nada resolve nos primeiros
#: minutos, a maior parte resolve entre 30 e 90 minutos. Consultar a cada 60s
#: durante 10 horas gastaria 600 chamadas de API por pedido para ganhar o mesmo
#: resultado que ~20 consultas espacadas.
BACKOFF_MINUTOS = (1, 2, 5, 10, 15, 20, 30, 30, 45, 60)

#: Idade maxima do item antes de desistir. Coberto com folga sobre o p90 de
#: 90 min: um pedido que nao apareceu no Bling em 24h nao vai aparecer sozinho.
HORIZONTE_HORAS = int(os.getenv("ERP_REFERENCE_HORIZON_HOURS", "24"))


def _proxima_tentativa_iso(attempts: int) -> str:
    """Momento da proxima consulta, com backoff progressivo."""
    indice = min(attempts, len(BACKOFF_MINUTOS) - 1)
    minutos = BACKOFF_MINUTOS[indice]
    return (datetime.now(timezone.utc) + timedelta(minutes=minutos)).isoformat()


def _excedeu_horizonte(created_at: Any) -> bool:
    if not created_at:
        return False
    try:
        nascido = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if nascido.tzinfo is None:
        nascido = nascido.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - nascido > timedelta(hours=HORIZONTE_HORAS)


def _situacoes_por_pedido(pedido_ids: list) -> dict:
    if not pedido_ids:
        return {}
    rows = (
        supabase_db.table("pedidos")
        .select("id,situacao_pedido_id")
        .in_("id", pedido_ids)
        .execute()
        .data
        or []
    )
    return {row["id"]: row.get("situacao_pedido_id") for row in rows}


@shared_task(name="nistiprint_shared.services.order_erp_reference_service.reconcile_pending")
@log_task_execution(task_type="PEDIDO", task_name="reconcile_pending_erp_references")
def reconcile_pending_erp_references(limit: int = 50):
    agora = get_now_iso()
    rows = (
        supabase_db.table("pending_order_reconciliations")
        .select("id,pedido_id,attempts,created_at")
        .eq("status", "pending")
        .eq("reason", "erp_reference_pending")
        .or_(f"next_attempt_after.is.null,next_attempt_after.lte.{agora}")
        .order("updated_at")
        .limit(limit)
        .execute()
        .data
        or []
    )

    # Encerra os terminais antes de gastar chamada ao Bling. `skipped_terminal`
    # e distinto de `failed` de proposito: um pedido devolvido nao e um item que
    # falhou, e um item que nao tinha o que resolver. Misturar os dois faz a
    # fila de falhas parecer um problema quando nao e — e esconde as falhas de
    # verdade no meio.
    situacoes = _situacoes_por_pedido([r.get("pedido_id") for r in rows if r.get("pedido_id")])
    terminais = [r for r in rows if situacoes.get(r.get("pedido_id")) in TERMINAL_SITUACAO_IDS]
    for row in terminais:
        supabase_db.table("pending_order_reconciliations").update({
            "status": "skipped_terminal",
            "last_error": "Pedido em situacao terminal; nao tera referencia de ERP",
            "resolved_at": get_now_iso(),
            "updated_at": get_now_iso(),
        }).eq("id", row.get("id")).execute()
    if terminais:
        logger.info(
            "Reconciliacao ERP: %s pedidos encerrados por situacao terminal", len(terminais)
        )

    ativos = [r for r in rows if r not in terminais]
    batch = _resolve_pending_references_in_batch(ativos)
    ready_ids = [item.get("pedido_id") for item in batch["ready"]]
    esgotados = 0
    esgotados_pedidos: list[int] = []

    for row in ativos:
        if row.get("pedido_id") in ready_ids:
            continue
        result = next(
            (item for item in batch["blocked"] if item.get("pedido_id") == row.get("pedido_id")),
            {},
        )
        motivo = result.get("message") or result.get("status") or "Motivo desconhecido"
        attempts = int(row.get("attempts") or 0) + 1

        # Desistencia por idade, nao por contagem. A contagem media a paciencia
        # em consultas; o que importa e ha quanto tempo o pedido existe sem
        # aparecer no Bling.
        esgotou = _excedeu_horizonte(row.get("created_at"))
        if esgotou:
            esgotados += 1
            esgotados_pedidos.append(row.get("pedido_id"))

        # Motivo de cada item nao aplicado, por pedido. Antes so ficava no
        # last_error da tabela — invisivel no log da task, entao "processed 4,
        # applied 1" nao dizia por que os outros 3 nao aplicaram, e um pedido
        # podia empilhar dezenas de tentativas sem ninguem perceber.
        logger.info(
            "Reconciliacao ERP: pedido %s nao aplicado (tentativa %s%s): %s",
            row.get("pedido_id"),
            attempts,
            ", ESGOTOU horizonte" if esgotou else "",
            motivo,
        )

        supabase_db.table("pending_order_reconciliations").update({
            "attempts": attempts,
            "status": "failed" if esgotou else "pending",
            "next_attempt_after": None if esgotou else _proxima_tentativa_iso(attempts),
            "last_error": motivo,
            "updated_at": get_now_iso(),
        }).eq("id", row.get("id")).execute()

    if esgotados:
        # Um pedido que desiste aqui nao pode ser faturado nem impresso. Antes
        # isso acontecia em silencio: o item so mudava de status no banco e
        # ninguem era avisado.
        logger.error(
            "Reconciliacao ERP: %s pedidos passaram de %sh sem referencia de ERP "
            "(pedido_id: %s) — nao serao faturaveis nem imprimiveis ate intervencao manual",
            esgotados,
            HORIZONTE_HORAS,
            ", ".join(str(p) for p in esgotados_pedidos),
        )

    return {
        "status": "success",
        "processed": len(rows),
        "applied": len(batch["ready"]),
        "skipped_terminal": len(terminais),
        "exhausted": esgotados,
    }
