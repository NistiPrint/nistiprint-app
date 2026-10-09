"""Durable user-owned background operation tracking."""

import logging
from datetime import datetime, timezone
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.notification_service import notification_service

logger = logging.getLogger(__name__)


class AsyncOperationService:
    ACTIVE_STATUSES = ("AGUARDANDO", "EM_ANDAMENTO")
    TERMINAL_STATUSES = ("CONCLUIDO", "ERRO")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def _publish(self, operation: dict[str, Any], event_type="operation.updated"):
        owner = operation.get("owner_user_id")
        if owner is None:
            return
        notification_service.publish_user_event(str(owner), {
            "type": event_type,
            "operation": operation,
        })

    def create_operation(
        self,
        *,
        owner_user_id: int,
        categoria: str,
        titulo: str,
        mensagem: str = "",
        referencia_tipo: str | None = None,
        referencia_id: str | int | None = None,
        rota_destino: str | None = None,
        progresso_total: int | None = None,
        origem_tipo: str | None = None,
        origem_id: str | None = None,
        dados_adicionais: dict | None = None,
    ) -> dict:
        now = self._now()
        record = {
            "owner_user_id": int(owner_user_id),
            "categoria": categoria,
            "titulo": titulo,
            "mensagem": mensagem,
            "status": "AGUARDANDO",
            "referencia_tipo": referencia_tipo,
            "referencia_id": str(referencia_id) if referencia_id is not None else None,
            "rota_destino": rota_destino,
            "progresso_atual": 0 if progresso_total is not None else None,
            "progresso_total": progresso_total,
            "origem_tipo": origem_tipo,
            "origem_id": str(origem_id) if origem_id is not None else None,
            "dados_adicionais": dados_adicionais or {},
            "created_at": now,
            "updated_at": now,
        }
        response = supabase_db.table("operacoes_assincronas").insert(record).execute()
        if not response.data:
            raise RuntimeError("Não foi possível registrar o processo assíncrono.")
        operation = response.data[0]
        self._publish(operation)
        return operation

    def find_by_source(self, origem_tipo: str, origem_id: str | int) -> dict | None:
        response = (
            supabase_db.table("operacoes_assincronas")
            .select("*")
            .eq("origem_tipo", origem_tipo)
            .eq("origem_id", str(origem_id))
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None

    def sync_ai_batch(self, batch: dict) -> dict | None:
        """Mirror the durable AI batch state without taking ownership of its queue."""
        if not batch.get('id'):
            return None
        owner = batch.get("iniciado_por")
        if not owner:
            return None
        try:
            owner = int(owner)
        except (TypeError, ValueError):
            logger.warning("Ignoring AI batch with invalid owner id: %r", owner)
            return None

        raw_status = str(batch.get("status") or "PENDENTE").upper()
        status = {
            "PENDENTE": "AGUARDANDO",
            "RODANDO": "EM_ANDAMENTO",
            "CONCLUIDO": "CONCLUIDO",
            "ERRO": "ERRO",
        }.get(raw_status, "EM_ANDAMENTO")
        processed = int(batch.get("processados") or 0)
        total = int(batch.get("total") or 0)
        success = int(batch.get("sucesso") or 0)
        failed = int(batch.get("falha") or 0)
        operation = self.find_by_source("ai_batch", batch.get("id"))
        now = self._now()
        values = {
            "owner_user_id": owner,
            "categoria": "IA",
            "titulo": "Processamento de personalizações com IA",
            "mensagem": f"{processed} de {total} pedidos processados",
            "status": status,
            "referencia_tipo": "ai_batch",
            "referencia_id": str(batch.get("id")),
            "rota_destino": "/vendas/personalizadas",
            "etapa": "Na fila" if status == "AGUARDANDO" else ("Concluído" if status == "CONCLUIDO" else ("Falhou" if status == "ERRO" else "Processando pedidos")),
            "progresso_atual": processed,
            "progresso_total": total,
            "erro_resumo": f"{failed} pedido(s) com falha" if failed else None,
            "origem_tipo": "ai_batch",
            "origem_id": str(batch.get("id")),
            "dados_adicionais": {"sucesso": success, "falha": failed},
            "updated_at": now,
            "finalizado_em": batch.get("finalizado_em") if status in self.TERMINAL_STATUSES else None,
        }

        if operation:
            values.pop("owner_user_id", None)
            values.pop("categoria", None)
            values.pop("titulo", None)
            values.pop("origem_tipo", None)
            values.pop("origem_id", None)
            values.pop("created_at", None)
            return self.update_operation(operation["id"], **values)
        else:
            values["created_at"] = batch.get("criado_em") or now
            try:
                response = supabase_db.table("operacoes_assincronas").insert(values).execute()
            except Exception:
                # The unique origin index protects simultaneous batch events.
                duplicate = self.find_by_source("ai_batch", batch.get("id"))
                if duplicate:
                    return self.sync_ai_batch(batch)
                raise

        if not response.data:
            return None
        current = response.data[0]
        self._publish(current)
        if current.get("status") in self.TERMINAL_STATUSES:
            self._notify_terminal(current)
        return current

    def update_operation(self, operation_id: str, **changes) -> dict | None:
        current_response = (
            supabase_db.table("operacoes_assincronas")
            .select("*")
            .eq("id", operation_id)
            .maybe_single()
            .execute()
        )
        previous = current_response.data
        if not previous:
            return None
        previous_status = previous.get('status')
        requested_status = changes.get('status', previous_status)
        allowed_statuses = self.TERMINAL_STATUSES + self.ACTIVE_STATUSES
        if requested_status not in allowed_statuses:
            raise ValueError("Status de operação desconhecido.")
        if previous_status in self.TERMINAL_STATUSES:
            # Once a durable operation is terminal, stale queue events cannot
            # restart it or replace its outcome.
            return previous
        if previous_status == "EM_ANDAMENTO" and requested_status == "AGUARDANDO":
            # A delayed queue event must not make an in-flight operation look
            # as if it had returned to the waiting queue.
            return previous
        old_progress = previous.get("progresso_atual")
        new_progress = changes.get("progresso_atual")
        if old_progress is not None and new_progress is not None:
            try:
                if int(new_progress) < int(old_progress):
                    changes["progresso_atual"] = old_progress
                    changes["mensagem"] = previous.get("mensagem")
            except (TypeError, ValueError):
                changes["progresso_atual"] = old_progress
                changes["mensagem"] = previous.get("mensagem")
        changes["updated_at"] = self._now()
        if changes.get("status") in self.TERMINAL_STATUSES and not changes.get("finalizado_em"):
            changes["finalizado_em"] = self._now()
        response = (
            supabase_db.table("operacoes_assincronas")
            .update(changes)
            .eq("id", operation_id)
            .eq("owner_user_id", previous["owner_user_id"])
            .eq("updated_at", previous["updated_at"])
            .execute()
        )
        if not response.data:
            latest = (
                supabase_db.table("operacoes_assincronas")
                .select("*")
                .eq("id", operation_id)
                .maybe_single()
                .execute()
            ).data
            return latest
        operation = response.data[0]
        self._publish(operation)
        if operation.get("status") in self.TERMINAL_STATUSES and operation.get("status") != previous.get("status"):
            self._notify_terminal(operation)
        return operation

    def _notify_terminal(self, operation: dict):
        details = operation.get("dados_adicionais") or {}
        failed_count = int(details.get("falha") or details.get("falhas") or details.get("erro") or 0)
        success_count = int(details.get("sucesso") or 0)
        failed = operation.get("status") == "ERRO" or failed_count > 0
        title = "Processo concluído com falha" if failed else "Processo concluído"
        message = operation.get("erro_resumo") or operation.get("mensagem") or operation.get("titulo")
        if failed_count > 0:
            message = f"{success_count} concluído(s) com sucesso; {failed_count} com falha."
        event_type = "operation.failed" if failed else "operation.completed"
        try:
            notification_id = notification_service.create_notification(
                event_type=event_type,
                user_id=str(operation["owner_user_id"]),
                payload={
                    "title": title,
                    "message": message,
                    "tipo": "erro" if failed else "informativo",
                    "operation_id": operation["id"],
                    "rota_destino": operation.get("rota_destino"),
                    "categoria": operation.get("categoria"),
                },
            )
            self._publish({**operation, "notification_id": notification_id}, event_type)
        except Exception:
            logger.exception("Could not save terminal notification for operation %s", operation.get("id"))

    def list_center(self, owner_user_id: int, *, limit: int = 50, offset: int = 0) -> dict:
        stop = offset + limit - 1
        active = (
            supabase_db.table("operacoes_assincronas")
            .select("*")
            .eq("owner_user_id", int(owner_user_id))
            .in_("status", list(self.ACTIVE_STATUSES))
            .order("updated_at", desc=True)
            .range(0, stop)
            .execute()
            .data
            or []
        )
        recent = (
            supabase_db.table("operacoes_assincronas")
            .select("*")
            .eq("owner_user_id", int(owner_user_id))
            .in_("status", list(self.TERMINAL_STATUSES))
            .order("finalizado_em", desc=True)
            .range(0, stop)
            .execute()
            .data
            or []
        )
        notifications = (
            supabase_db.table("notificacoes")
            .select("id,owner_user_id,operacao_id,event_type,titulo,mensagem,tipo,nivel_critica,lida,read_at,data_envio,created_at,dados_adicionais")
            .eq("owner_user_id", int(owner_user_id))
            .order("created_at", desc=True)
            .range(offset, stop)
            .execute()
        )
        unread_response = (
            supabase_db.table("notificacoes")
            .select("id", count="exact", head=True)
            .eq("owner_user_id", int(owner_user_id))
            .eq("lida", False)
            .execute()
        )
        active_count = (supabase_db.table("operacoes_assincronas")
                        .select("id", count="exact", head=True)
                        .eq("owner_user_id", int(owner_user_id))
                        .in_("status", list(self.ACTIVE_STATUSES)).execute())
        recent_count = (supabase_db.table("operacoes_assincronas")
                        .select("id", count="exact", head=True)
                        .eq("owner_user_id", int(owner_user_id))
                        .in_("status", list(self.TERMINAL_STATUSES)).execute())
        notification_count = (supabase_db.table("notificacoes")
                              .select("id", count="exact", head=True)
                              .eq("owner_user_id", int(owner_user_id)).execute())
        notification_rows = notifications.data or []
        operation_by_id = {item["id"]: item for item in active + recent}
        merged = sorted(operation_by_id.values(), key=lambda item: item.get("updated_at") or "", reverse=True)
        operations = merged[offset:offset + limit]
        return {
            "operations": operations,
            "notifications": notification_rows,
            "unread_count": int(getattr(unread_response, "count", 0) or 0),
            "pagination": {
                "limit": limit,
                "offset": offset,
                "operations_total": int(getattr(active_count, "count", 0) or 0) + int(getattr(recent_count, "count", 0) or 0),
                "notifications_total": int(getattr(notification_count, "count", 0) or 0),
            },
        }

    def mark_notification_read(self, owner_user_id: int, notification_id: int) -> dict | None:
        now = self._now()
        response = (
            supabase_db.table("notificacoes")
            .update({"lida": True, "read_at": now, "data_visualizacao": now, "updated_at": now})
            .eq("id", int(notification_id))
            .eq("owner_user_id", int(owner_user_id))
            .execute()
        )
        return response.data[0] if response.data else None

    def get_user_operation(self, owner_user_id: int, operation_id: str) -> dict | None:
        response = (
            supabase_db.table("operacoes_assincronas")
            .select("*")
            .eq("id", operation_id)
            .eq("owner_user_id", int(owner_user_id))
            .maybe_single()
            .execute()
        )
        return response.data


async_operation_service = AsyncOperationService()
