from __future__ import annotations

import logging
import os
from typing import Any

from celery import shared_task

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_repository import canonical_order_repository
from nistiprint_shared.services.integration_capability_service import INVOICING, integration_capability_service
from nistiprint_shared.utils.date_utils import get_now_iso
from nistiprint_shared.utils.task_logging import log_task_execution

logger = logging.getLogger(__name__)


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
                "erp_integration_id,erp_store_id,erp_order_id,erp_order_number,"
                "bling_integration_id,bling_loja_id,bling_order_id,bling_order_number"
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
                "erp_store_id": pedido.get("erp_store_id") or pedido.get("bling_loja_id"),
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

        try:
            client = BlingClient.create_client_for_integration_id(erp_integration_id)
            matches = client.get_order_numbers_by_store_numbers([external_order_id]) or []
        except Exception as exc:
            logger.warning("Falha ao resolver ERP do pedido %s: %s", pedido_id, exc, exc_info=True)
            return {"status": "error", "pedido_id": pedido_id, "message": str(exc)}

        exact = [
            row for row in matches
            if str(row.get("numeroLoja") or external_order_id).strip() == external_order_id
            and row.get("id") and row.get("numero")
        ]
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
        integration_id = pedido.get("erp_integration_id") or pedido.get("bling_integration_id")
        order_id = pedido.get("erp_order_id") or pedido.get("bling_order_id")
        order_number = pedido.get("erp_order_number") or pedido.get("bling_order_number")
        if not integration_id or not order_id or not order_number:
            return None
        return {
            "erp_integration_id": int(integration_id),
            "erp_store_id": pedido.get("erp_store_id") or pedido.get("bling_loja_id"),
            "erp_order_id": order_id,
            "erp_order_number": str(order_number),
        }



def _resolve_pending_references_in_batch(rows: list[dict]) -> dict:
    """Consulta numeroLoja agrupando pedidos pela mesma conta Bling."""
    from nistiprint_shared.services.bling.bling_client import BlingClient
    grouped = {}
    results = []
    for row in rows:
        pedido = (supabase_db.table("pedidos")
            .select("id,marketplace_order_id,marketplace_integration_id,erp_store_id,bling_loja_id")
            .eq("id", row.get("pedido_id")).limit(1).execute().data or [])
        if not pedido:
            results.append({"status": "not_found", "pedido_id": row.get("pedido_id")})
            continue
        pedido = pedido[0]
        resolved = integration_capability_service.resolve(
            pedido.get("marketplace_integration_id"), INVOICING,
            context={"erp_store_id": pedido.get("erp_store_id") or pedido.get("bling_loja_id"),
                     "external_order_id": pedido.get("marketplace_order_id")})
        if not resolved.responsible_integration or resolved.reason == "ambiguous_erp_link":
            results.append({"status": "missing_link", "pedido_id": pedido["id"]})
            continue
        link = resolved.link or {}
        key = (int(resolved.integration_id), str(link.get("erp_store_id") or link.get("aggregator_store_id") or ""))
        grouped.setdefault(key, []).append(pedido)
    for (integration_id, store_id), pedidos in grouped.items():
        ids = [str(p["marketplace_order_id"]) for p in pedidos if p.get("marketplace_order_id")]
        try:
            matches = BlingClient.create_client_for_integration_id(integration_id).get_order_numbers_by_store_numbers(ids) or []
        except Exception as exc:
            logger.warning("Falha no lote de referencias Bling: %s", exc, exc_info=True)
            results.extend({"status": "error", "pedido_id": p["id"], "message": str(exc)} for p in pedidos)
            continue
        by_store = {str(m.get("numeroLoja")): m for m in matches if m.get("numeroLoja") and m.get("id") and m.get("numero")}
        for pedido in pedidos:
            match = by_store.get(str(pedido.get("marketplace_order_id")))
            if not match:
                results.append({"status": "pending", "pedido_id": pedido["id"], "message": "Pedido ainda nao encontrado no ERP"})
                continue
            supabase_db.rpc("enrich_order_erp_reference", {
                "p_pedido_id": pedido["id"], "p_erp_integration_id": integration_id,
                "p_erp_store_id": store_id or None, "p_erp_order_id": match["id"],
                "p_erp_order_number": str(match["numero"]),
                "p_marketplace_order_id": pedido.get("marketplace_order_id"),
            }).execute()
            results.append({"status": "ready", "pedido_id": pedido["id"]})
    return {"ready": [r for r in results if r["status"] == "ready"],
            "blocked": [r for r in results if r["status"] != "ready"]}

order_erp_reference_service = OrderErpReferenceService()


@shared_task(name="nistiprint_shared.services.order_erp_reference_service.reconcile_pending")
@log_task_execution(task_type="PEDIDO", task_name="reconcile_pending_erp_references")
def reconcile_pending_erp_references(limit: int = 50):
    rows = (
        supabase_db.table("pending_order_reconciliations")
        .select("id,pedido_id,attempts")
        .eq("status", "pending")
        .eq("reason", "erp_reference_pending")
        .order("updated_at")
        .limit(limit)
        .execute()
        .data
        or []
    )
    batch = _resolve_pending_references_in_batch(rows)
    ready_ids = [item.get("pedido_id") for item in batch["ready"]]
    for row in rows:
        if row.get("pedido_id") in ready_ids:
            continue
        result = next((item for item in batch["blocked"] if item.get("pedido_id") == row.get("pedido_id")), {})
        attempts = int(row.get("attempts") or 0) + 1
        max_attempts = int(os.getenv("ERP_REFERENCE_MAX_ATTEMPTS", "20"))
        supabase_db.table("pending_order_reconciliations").update({
            "attempts": attempts,
            "status": "failed" if attempts >= max_attempts else "pending",
            "last_error": result.get("message") or result.get("status"),
            "updated_at": get_now_iso(),
        }).eq("id", row.get("id")).execute()
    return {"status": "success", "processed": len(rows), "applied": len(batch["ready"])}
