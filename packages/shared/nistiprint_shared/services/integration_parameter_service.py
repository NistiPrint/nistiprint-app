"""Layered integration settings and bidirectional provider equivalences."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.canonical_order_repository import CanonicalOrderRepository


class IntegrationParameterService:
    """Resolve module defaults -> installation -> ERP/marketplace link overrides."""

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = deepcopy(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = IntegrationParameterService._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    def effective_config(
        self,
        module_id: str,
        *,
        integration_id: Optional[int] = None,
        erp_marketplace_link_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        module_id = CanonicalOrderRepository.normalize_module_id(module_id)
        module_rows = (
            supabase_db.table("integration_modules")
            .select("data_mapping_spec")
            .eq("id", module_id)
            .limit(1).execute().data or []
        )
        mapping_spec = (module_rows[0].get("data_mapping_spec") or {}) if module_rows else {}
        config = mapping_spec.get("defaults") or mapping_spec.get("config_defaults") or {}

        if integration_id:
            rows = (
                supabase_db.table("installed_integrations")
                .select("config")
                .eq("id", integration_id)
                .limit(1).execute().data or []
            )
            if rows:
                config = self._deep_merge(config, rows[0].get("config") or {})

        if erp_marketplace_link_id:
            rows = (
                supabase_db.table("erp_marketplace_links")
                .select("config")
                .eq("id", erp_marketplace_link_id)
                .limit(1).execute().data or []
            )
            if rows:
                config = self._deep_merge(config, rows[0].get("config") or {})
        return config

    def resolve_equivalence(
        self,
        module_id: str,
        domain: str,
        value: Any,
        *,
        direction: str = "inbound",
        integration_id: Optional[int] = None,
        erp_marketplace_link_id: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        if direction not in ("inbound", "outbound"):
            raise ValueError("direction must be inbound or outbound")
        module_id = CanonicalOrderRepository.normalize_module_id(module_id)
        rows = (
            supabase_db.table("integration_mapping_rules")
            .select("*")
            .eq("module_id", module_id)
            .eq("domain", domain)
            .eq("direction", direction)
            .eq("is_active", True)
            .execute().data or []
        )
        needle = str(value)
        candidates = []
        for row in rows:
            source_value = row.get("provider_value") if direction == "inbound" else row.get("internal_value")
            if str(source_value) != needle:
                continue
            row_integration = row.get("integration_id")
            row_link = row.get("erp_marketplace_link_id")
            if row_link is not None and str(row_link) != str(erp_marketplace_link_id):
                continue
            if row_link is None and row_integration is not None and str(row_integration) != str(integration_id):
                continue
            scope_rank = 2 if row_link is not None else 1 if row_integration is not None else 0
            candidates.append((scope_rank, int(row.get("priority") or 0), row))
        if not candidates:
            return value if default is None else default
        selected = max(candidates, key=lambda item: (item[0], item[1]))[2]
        return selected.get("internal_value") if direction == "inbound" else selected.get("provider_value")


integration_parameter_service = IntegrationParameterService()

