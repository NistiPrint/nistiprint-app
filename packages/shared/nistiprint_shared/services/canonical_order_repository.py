"""Atomic persistence for canonical marketplace orders.

All order writers should use this repository so identity, snapshots and provider
references are committed by the same database transaction.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

from postgrest.exceptions import APIError

from nistiprint_shared.database.supabase_db_service import supabase_db


class CanonicalOrderIdentityError(ValueError):
    """Raised when a marketplace order cannot be assigned a stable identity."""


class OrderIdentityUnresolvedError(CanonicalOrderIdentityError):
    """Raised after an ERP order is deferred for marketplace reconciliation."""


class CanonicalOrderRepository:
    MODULE_ALIASES = {
        "shopee": "shopee",
        "mercadolivre": "mercadolivre",
        "mercado_livre": "mercadolivre",
        "mercado-livre": "mercadolivre",
        "meli": "mercadolivre",
        "ml": "mercadolivre",
    }

    @classmethod
    def normalize_module_id(cls, value: Any) -> Optional[str]:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        return cls.MODULE_ALIASES.get(normalized, normalized)

    @staticmethod
    def normalize_order_id(value: Any) -> Optional[str]:
        normalized = str(value or "").strip()
        return normalized or None

    def resolve_module_id(
        self,
        marketplace_integration_id: Optional[int] = None,
        explicit_module_id: Any = None,
    ) -> Optional[str]:
        explicit = self.normalize_module_id(explicit_module_id)
        if explicit:
            return explicit
        if not marketplace_integration_id:
            return None

        response = (
            supabase_db.table("installed_integrations")
            .select("module_id")
            .eq("id", marketplace_integration_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return self.normalize_module_id(rows[0].get("module_id")) if rows else None

    def resolve_erp_marketplace_link(
        self,
        erp_integration_id: Optional[int],
        erp_store_id: Any,
    ) -> Optional[Dict[str, Any]]:
        if not erp_integration_id or erp_store_id in (None, ""):
            return None
        response = (
            supabase_db.table("erp_marketplace_links")
            .select("marketplace_module_id,marketplace_integration_id,erp_store_id")
            .eq("erp_integration_id", erp_integration_id)
            .eq("erp_store_id", str(erp_store_id))
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        row = dict(rows[0])
        row["marketplace_module_id"] = self.normalize_module_id(
            row.get("marketplace_module_id")
        )
        return row

    def upsert(
        self,
        order: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]] = None,
        refs: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> int:
        payload = dict(order or {})
        payload["marketplace_module_id"] = self.resolve_module_id(
            payload.get("marketplace_integration_id"),
            payload.get("marketplace_module_id"),
        )
        payload["marketplace_order_id"] = self.normalize_order_id(
            payload.get("marketplace_order_id")
            or payload.get("codigo_pedido_externo")
        )
        if not payload["marketplace_module_id"] or not payload["marketplace_order_id"]:
            raise CanonicalOrderIdentityError(
                "marketplace_module_id and marketplace_order_id are required"
            )

        snapshot_payload = self._json_safe(snapshot) if snapshot is not None else None
        refs_payload = self._json_safe(list(refs or []))

        try:
            response = self._execute_upsert_rpc(payload, snapshot_payload, refs_payload)
        except APIError as exc:
            if not self._is_duplicate_mirror_link_error(exc, payload):
                raise
            self._reconcile_duplicate_mirror_identity(exc, payload)
            response = self._execute_upsert_rpc(payload, snapshot_payload, refs_payload)
        value = response.data
        if isinstance(value, list):
            value = value[0] if value else None
            if isinstance(value, dict):
                value = value.get("upsert_canonical_order") or value.get("id")
        elif isinstance(value, dict):
            value = value.get("upsert_canonical_order") or value.get("id")
        if value is None:
            raise RuntimeError("upsert_canonical_order returned no pedido id")
        return int(value)

    def apply_marketplace_event(
        self,
        order: Dict[str, Any],
        *,
        lifecycle_event: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]] = None,
        refs: Optional[Iterable[Dict[str, Any]]] = None,
        projection_enabled: bool = False,
    ) -> Dict[str, Any]:
        payload = dict(order or {})
        payload["marketplace_module_id"] = self.resolve_module_id(
            payload.get("marketplace_integration_id"),
            payload.get("marketplace_module_id"),
        )
        payload["marketplace_order_id"] = self.normalize_order_id(
            payload.get("marketplace_order_id")
            or payload.get("codigo_pedido_externo")
        )
        if not payload["marketplace_module_id"] or not payload["marketplace_order_id"]:
            raise CanonicalOrderIdentityError(
                "marketplace_module_id and marketplace_order_id are required"
            )
        try:
            response = self._execute_apply_event_rpc(
                payload,
                self._json_safe(snapshot) if snapshot is not None else None,
                self._json_safe(list(refs or [])),
                self._json_safe(lifecycle_event or {}),
                bool(projection_enabled),
            )
        except APIError as exc:
            if not self._is_duplicate_mirror_link_error(exc, payload):
                raise
            self._reconcile_duplicate_mirror_identity(exc, payload)
            response = self._execute_apply_event_rpc(
                payload,
                self._json_safe(snapshot) if snapshot is not None else None,
                self._json_safe(list(refs or [])),
                self._json_safe(lifecycle_event or {}),
                bool(projection_enabled),
            )
        value = response.data
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, dict) or value.get("pedido_id") is None:
            raise RuntimeError("apply_marketplace_order_event returned no pedido id")
        return value

    def _execute_upsert_rpc(
        self,
        payload: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
        refs: Any,
    ):
        return supabase_db.rpc(
            "upsert_canonical_order",
            {
                "p_order": self._json_safe(payload),
                "p_snapshot": snapshot,
                "p_refs": refs,
            },
        ).execute()

    def _execute_apply_event_rpc(
        self,
        payload: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
        refs: Any,
        lifecycle_event: Dict[str, Any],
        projection_enabled: bool,
    ):
        return supabase_db.rpc(
            "apply_marketplace_order_event",
            {
                "p_order": self._json_safe(payload),
                "p_snapshot": snapshot,
                "p_refs": refs,
                "p_event": lifecycle_event,
                "p_projection_enabled": projection_enabled,
            },
        ).execute()

    DUPLICATE_MIRROR_LINKS = {
        "ux_pedidos_pedido_bling_id": "pedido_bling_id",
        "ux_pedidos_pedido_meli_id": "pedido_mercadolivre_id",
        "ux_pedidos_pedido_shopee_id": "pedido_shopee_id",
    }

    def _detect_duplicate_mirror_field(self, exc: APIError, payload: Dict[str, Any]) -> Optional[str]:
        if str(getattr(exc, "code", "")) != "23505":
            return None
        details = str(getattr(exc, "details", "") or "")
        message = str(getattr(exc, "message", "") or "")
        for constraint_name, field_name in self.DUPLICATE_MIRROR_LINKS.items():
            if payload.get(field_name) in (None, ""):
                continue
            if constraint_name in details or constraint_name in message:
                return field_name
        return None

    def _is_duplicate_mirror_link_error(self, exc: APIError, payload: Dict[str, Any]) -> bool:
        return self._detect_duplicate_mirror_field(exc, payload) is not None

    def _find_existing_order_by_mirror_link(self, field_name: str, field_value: Any) -> Optional[Dict[str, Any]]:
        response = (
            supabase_db.table("pedidos")
            .select("id,marketplace_module_id,marketplace_order_id")
            .eq(field_name, field_value)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return dict(rows[0]) if rows else None

    def _reconcile_duplicate_mirror_identity(self, exc: APIError, payload: Dict[str, Any]) -> None:
        field_name = self._detect_duplicate_mirror_field(exc, payload)
        if not field_name:
            return

        existing = self._find_existing_order_by_mirror_link(field_name, payload.get(field_name))
        if not existing:
            return

        existing_id = existing.get("id")
        if not existing_id:
            return

        incoming_module = self.normalize_module_id(payload.get("marketplace_module_id"))
        incoming_order = self.normalize_order_id(payload.get("marketplace_order_id"))
        existing_module = self.normalize_module_id(existing.get("marketplace_module_id"))
        existing_order = self.normalize_order_id(existing.get("marketplace_order_id"))

        if not incoming_module or not incoming_order:
            return
        if incoming_module == existing_module and incoming_order == existing_order:
            return

        if existing_module and existing_order:
            supabase_db.rpc(
                "correct_canonical_order_identity",
                {
                    "p_pedido_id": existing_id,
                    "p_marketplace_module_id": incoming_module,
                    "p_marketplace_order_id": incoming_order,
                    "p_reason": f"auto_reconcile_duplicate_{field_name}",
                    "p_actor_id": "canonical_order_repository",
                },
            ).execute()
            return

        (
            supabase_db.table("pedidos")
            .update(
                {
                    "marketplace_module_id": incoming_module,
                    "marketplace_order_id": incoming_order,
                    "codigo_pedido_externo": incoming_order,
                    "origem": incoming_module.upper(),
                }
            )
            .eq("id", existing_id)
            .execute()
        )

    def defer_unresolved_erp_order(
        self,
        *,
        pedido_id: Optional[int] = None,
        erp_integration_id: Optional[int],
        erp_store_id: Any,
        erp_order_id: Any,
        marketplace_order_id: Any,
        payload: Dict[str, Any],
        reason: str = "marketplace_module_unresolved",
    ) -> None:
        record = {
            "pedido_id": pedido_id,
            "erp_integration_id": erp_integration_id,
            "erp_store_id": self.normalize_order_id(erp_store_id),
            "erp_order_id": erp_order_id,
            "marketplace_order_id": self.normalize_order_id(marketplace_order_id),
            "reason": reason,
            "payload": self._json_safe(payload or {}),
            "status": "pending",
            "updated_at": datetime.utcnow().isoformat(),
        }
        query = supabase_db.table("pending_order_reconciliations")
        if pedido_id:
            existing = (
                query.select("id")
                .eq("pedido_id", pedido_id)
                .eq("status", "pending")
                .limit(1)
                .execute()
                .data
                or []
            )
            if existing:
                query.update(record).eq("id", existing[0]["id"]).execute()
            else:
                try:
                    query.insert(record).execute()
                except APIError as exc:
                    if str(getattr(exc, "code", "")) != "23505":
                        raise
                    query.update(record).eq("pedido_id", pedido_id).eq("status", "pending").execute()
            return
        if erp_integration_id and erp_order_id not in (None, ""):
            query.upsert(
                record,
                on_conflict="erp_integration_id,erp_order_id,status",
            ).execute()
            return
        query.insert(record).execute()

    def queue_marketplace_enrichment(
        self,
        *,
        marketplace_integration_id: int,
        marketplace_module_id: Any,
        marketplace_order_id: Any,
        payload: Dict[str, Any],
        event_type: Optional[str] = None,
        source_event_id: Optional[str] = None,
    ) -> None:
        module_id = self.normalize_module_id(marketplace_module_id)
        order_id = self.normalize_order_id(marketplace_order_id)
        if not module_id or not order_id:
            raise CanonicalOrderIdentityError(
                "Marketplace enrichment requires module and order identity"
            )
        record = {
            "marketplace_integration_id": marketplace_integration_id,
            "marketplace_module_id": module_id,
            "marketplace_order_id": order_id,
            "event_type": event_type,
            "source_event_id": source_event_id,
            "payload": self._json_safe(payload or {}),
            "status": "pending",
            "updated_at": datetime.utcnow().isoformat(),
        }
        (
            supabase_db.table("pending_marketplace_enrichments")
            .upsert(
                record,
                on_conflict="marketplace_integration_id,marketplace_order_id,source_event_id",
            )
            .execute()
        )

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (datetime, date, UUID, Decimal)):
            return str(value)
        return value


canonical_order_repository = CanonicalOrderRepository()

