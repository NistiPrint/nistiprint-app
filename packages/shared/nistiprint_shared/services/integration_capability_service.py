from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.models.integration_module import InstalledIntegration


ORDER_IMPORT = "ORDER_IMPORT"
ORDER_UPDATE = "ORDER_UPDATE"
WEBHOOK_INGEST = "WEBHOOK_INGEST"
INVOICING = "INVOICING"
TOKEN_REFRESH = "TOKEN_REFRESH"
CONNECTION_TEST = "CONNECTION_TEST"

MARKETPLACE_DIRECT_CAPABILITIES = {ORDER_IMPORT, ORDER_UPDATE, WEBHOOK_INGEST}
LOCAL_CAPABILITIES = {TOKEN_REFRESH, CONNECTION_TEST}


@dataclass
class CapabilityResolution:
    capability: str
    requested_integration_id: str | None
    responsible_integration: InstalledIntegration | None
    source: str
    mode: str | None = None
    link: dict | None = None
    reason: str | None = None

    @property
    def integration_id(self) -> str | None:
        if not self.responsible_integration:
            return None
        return str(self.responsible_integration.id)

    def to_dict(self) -> dict:
        return {
            "capability": self.capability,
            "requested_integration_id": self.requested_integration_id,
            "responsible_integration_id": self.integration_id,
            "responsible_module_id": self.responsible_integration.module_id if self.responsible_integration else None,
            "source": self.source,
            "mode": self.mode,
            "link": self.link,
            "reason": self.reason,
        }


def _as_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _has_scope(row: dict | None, capability: str | None) -> bool:
    if not row or not capability:
        return False
    scopes = _as_list(row.get("functional_scopes"))
    return capability in scopes


def _module_id(row: dict | None) -> str:
    return str((row or {}).get("module_id") or "").lower()


def _is_erp(row: dict | None) -> bool:
    module_id = _module_id(row)
    return module_id in {"bling"} or "erp" in module_id


def _to_integration(row: dict | None) -> InstalledIntegration | None:
    if not row:
        return None
    return InstalledIntegration.from_dict(dict(row), str(row.get("id")))


class IntegrationCapabilityService:
    """
    Resolves which installed integration is responsible for a system capability.

    Current canonical sources are ERP-marketplace links and channel_connections.
    Legacy fallbacks are preserved while the database model is being cleaned up.
    """

    def resolve(
        self,
        integration_id: str | int | None,
        capability: str | None,
        context: dict | None = None,
    ) -> CapabilityResolution:
        requested_id = str(integration_id) if integration_id is not None else None
        capability = str(capability or "").upper()
        context = context or {}
        if not requested_id:
            return CapabilityResolution(capability, None, None, "none", reason="missing_integration_id")

        requested = self._get_installation(requested_id)
        if not requested:
            return CapabilityResolution(capability, requested_id, None, "none", reason="integration_not_found")

        if capability in LOCAL_CAPABILITIES:
            return CapabilityResolution(capability, requested_id, _to_integration(requested), "self", mode="local")

        if capability == INVOICING:
            linked = self._resolve_linked_erp(requested_id, context)
            if linked.responsible_integration:
                linked.capability = capability
                return linked
            if linked.reason == "ambiguous_erp_link":
                return linked

        if capability in MARKETPLACE_DIRECT_CAPABILITIES:
            direct = self._resolve_ingest_source(requested_id, requested, capability)
            if direct.responsible_integration:
                return direct

        parent = self._resolve_parent(requested)
        if parent.responsible_integration and (not capability or _has_scope(parent.responsible_integration.to_dict(), capability) or _is_erp(parent.responsible_integration.to_dict())):
            parent.capability = capability
            return parent

        if capability and _has_scope(requested, capability):
            return CapabilityResolution(capability, requested_id, _to_integration(requested), "self", mode="functional_scope")

        default = self._resolve_default(capability)
        if default.responsible_integration:
            default.requested_integration_id = requested_id
            return default

        return CapabilityResolution(capability, requested_id, None, "none", reason="no_route_found")

    def resolve_integration(
        self,
        integration_id: str | int | None,
        capability: str | None,
        context: dict | None = None,
    ) -> InstalledIntegration | None:
        return self.resolve(integration_id, capability, context=context).responsible_integration

    def _get_installation(self, integration_id: str | int | None) -> dict | None:
        if integration_id is None:
            return None
        rows = (
            supabase_db.table("installed_integrations")
            .select("*")
            .eq("id", str(integration_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def _resolve_linked_erp(self, marketplace_integration_id: str, context: dict | None = None) -> CapabilityResolution:
        context = context or {}
        requested_erp_id = self._first_present(
            context,
            "bling_integration_id",
            "erp_integration_id",
            "responsible_erp_integration_id",
        )
        erp_store_id = self._first_present(
            context,
            "erp_store_id",
            "shop_id",
            "bling_loja_id",
            "aggregator_store_id",
        )
        default_erp_id, default_store_id, default_link_id = self._get_marketplace_default_nfe_route(marketplace_integration_id)

        if requested_erp_id:
            link = self._get_erp_marketplace_link(
                marketplace_integration_id,
                erp_integration_id=requested_erp_id,
                erp_store_id=erp_store_id,
            )
            erp = self._get_installation(requested_erp_id)
            if erp:
                return CapabilityResolution(
                    INVOICING,
                    marketplace_integration_id,
                    _to_integration(erp),
                    "order_context",
                    mode="erp",
                    link=link,
                )

        if default_erp_id and not requested_erp_id and not erp_store_id:
            link = self._get_erp_marketplace_link(
                marketplace_integration_id,
                erp_integration_id=default_erp_id,
                erp_store_id=default_store_id,
                link_id=default_link_id,
            )
            erp = self._get_installation(default_erp_id)
            if erp and link:
                return CapabilityResolution(
                    INVOICING,
                    marketplace_integration_id,
                    _to_integration(erp),
                    "marketplace_default_nfe",
                    mode="erp",
                    link=link,
                )

        if erp_store_id:
            link = self._get_erp_marketplace_link(
                marketplace_integration_id,
                erp_store_id=erp_store_id,
            )
            if link and link.get("erp_integration_id"):
                erp = self._get_installation(link.get("erp_integration_id"))
                if erp:
                    return CapabilityResolution(
                        INVOICING,
                        marketplace_integration_id,
                        _to_integration(erp),
                        "erp_marketplace_links",
                        mode="erp_store",
                        link=link,
                    )

        links = self._get_erp_marketplace_links(marketplace_integration_id)
        if len(links) == 1 and links[0].get("erp_integration_id"):
            erp = self._get_installation(links[0].get("erp_integration_id"))
            if erp:
                return CapabilityResolution(
                    INVOICING,
                    marketplace_integration_id,
                    _to_integration(erp),
                    "erp_marketplace_links",
                    mode="single_link",
                    link=links[0],
                )
        if len(links) > 1:
            return CapabilityResolution(
                INVOICING,
                marketplace_integration_id,
                None,
                "erp_marketplace_links",
                reason="ambiguous_erp_link",
                link={"matches": links},
            )

        if erp_store_id:
            channels = [self._get_channel_connection(marketplace_integration_id, erp_store_id=erp_store_id)]
            channels = [channel for channel in channels if channel]
        else:
            channels = self._get_channel_connections(marketplace_integration_id)
        if len(channels) > 1:
            return CapabilityResolution(
                INVOICING,
                marketplace_integration_id,
                None,
                "channel_connections",
                reason="ambiguous_erp_link",
                link={"matches": channels},
            )
        channel = channels[0] if channels else None
        if channel and channel.get("bling_integration_id"):
            erp = self._get_installation(channel.get("bling_integration_id"))
            if erp:
                return CapabilityResolution(
                    INVOICING,
                    marketplace_integration_id,
                    _to_integration(erp),
                    "channel_connections",
                    mode="erp",
                    link=channel,
                )

        return CapabilityResolution(INVOICING, marketplace_integration_id, None, "none", reason="no_erp_link")

    def _get_marketplace_default_nfe_route(self, marketplace_integration_id: str):
        marketplace = self._get_installation(marketplace_integration_id)
        config = (marketplace or {}).get("config") or {}
        return (
            self._first_present(config, "default_nfe_erp_integration_id", "default_nfe_bling_integration_id"),
            self._first_present(config, "default_nfe_shop_id", "default_nfe_erp_store_id"),
            self._first_present(config, "default_nfe_link_id", "default_nfe_erp_link_id"),
        )

    def _resolve_ingest_source(self, marketplace_integration_id: str, requested: dict, capability: str) -> CapabilityResolution:
        link = self._get_channel_connection(marketplace_integration_id) or self._get_erp_marketplace_link(marketplace_integration_id)
        mode = (link or {}).get("ingest_origin_mode")
        module_id = _module_id(requested)

        if mode == "marketplace_direct" or module_id in {"shopee", "mercadolivre"}:
            return CapabilityResolution(
                capability,
                marketplace_integration_id,
                _to_integration(requested),
                "ingest_origin_mode" if mode else "module_default",
                mode="marketplace_direct",
                link=link,
            )

        if mode in {"erp_bling", "erp_only_dummy"} and link:
            erp_id = link.get("bling_integration_id") or link.get("erp_integration_id")
            erp = self._get_installation(erp_id)
            if erp:
                return CapabilityResolution(
                    capability,
                    marketplace_integration_id,
                    _to_integration(erp),
                    "ingest_origin_mode",
                    mode=mode,
                    link=link,
                )

        return CapabilityResolution(capability, marketplace_integration_id, None, "none", reason="no_ingest_route")

    def _resolve_parent(self, requested: dict) -> CapabilityResolution:
        parent_id = requested.get("parent_integration_id")
        if not parent_id:
            return CapabilityResolution("", str(requested.get("id")), None, "none", reason="no_parent")
        parent = self._get_installation(parent_id)
        if not parent:
            return CapabilityResolution("", str(requested.get("id")), None, "none", reason="parent_not_found")
        return CapabilityResolution("", str(requested.get("id")), _to_integration(parent), "parent_integration_id", mode="parent")

    def _resolve_default(self, capability: str) -> CapabilityResolution:
        rows = (
            supabase_db.table("installed_integrations")
            .select("*")
            .eq("is_active", True)
            .eq("is_default", True)
            .execute()
            .data
            or []
        )
        for row in rows:
            row = dict(row)
            if _has_scope(row, capability):
                return CapabilityResolution(capability, None, _to_integration(row), "default_functional_scope", mode="default")
        return CapabilityResolution(capability, None, None, "none", reason="no_default")

    @staticmethod
    def _first_present(source: dict, *keys: str):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
        return None

    def _get_erp_marketplace_links(self, marketplace_integration_id: str) -> list[dict]:
        rows = (
            supabase_db.table("erp_marketplace_links")
            .select("*")
            .eq("marketplace_integration_id", int(marketplace_integration_id))
            .execute()
            .data
            or []
        )
        return [dict(row) for row in rows]

    def _get_erp_marketplace_link(
        self,
        marketplace_integration_id: str,
        erp_integration_id: str | int | None = None,
        erp_store_id: str | int | None = None,
        link_id: str | int | None = None,
    ) -> dict | None:
        query = (
            supabase_db.table("erp_marketplace_links")
            .select("*")
            .eq("marketplace_integration_id", int(marketplace_integration_id))
        )
        if link_id is not None:
            query = query.eq("id", str(link_id))
        if erp_integration_id is not None:
            query = query.eq("erp_integration_id", int(erp_integration_id))
        if erp_store_id is not None:
            query = query.eq("erp_store_id", str(erp_store_id))
        rows = (
            query
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def _get_channel_connection(
        self,
        marketplace_integration_id: str,
        erp_store_id: str | int | None = None,
    ) -> dict | None:
        query = (
            supabase_db.table("channel_connections")
            .select("*")
            .eq("marketplace_integration_id", int(marketplace_integration_id))
            .eq("is_active", True)
        )
        if erp_store_id is not None:
            query = query.eq("aggregator_store_id", str(erp_store_id))
        rows = (
            query
            .limit(1)
            .execute()
            .data
            or []
        )
        return dict(rows[0]) if rows else None

    def _get_channel_connections(self, marketplace_integration_id: str) -> list[dict]:
        rows = (
            supabase_db.table("channel_connections")
            .select("*")
            .eq("marketplace_integration_id", int(marketplace_integration_id))
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        return [dict(row) for row in rows]


integration_capability_service = IntegrationCapabilityService()
