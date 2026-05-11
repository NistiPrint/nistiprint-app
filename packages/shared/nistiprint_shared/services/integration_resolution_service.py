import time
from typing import Any, Dict, Iterable, Optional

from nistiprint_shared.database.supabase_db_service import supabase_db


class IntegrationResolutionService:
    """
    Mantém índices em memória para resolver integrações instaladas de forma
    parecida com o dict do legado, mas usando installed_integrations como
    fonte de verdade.

    Suporta aliases manuais nos configs:
    - Marketplace: shop_id, shop_ids, bling_loja_id, bling_loja_ids
    - ERP/Bling: company_id, company_ids, cnpj
    - Escopo opcional por marketplace: bling_integration_id, bling_integration_ids
    """

    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {
            "loaded_at": 0.0,
            "by_company_id": {},
            "by_cnpj": {},
            "by_shop_id": {},
            "marketplaces": [],
        }

    def _cache_expired(self) -> bool:
        return (time.time() - float(self._cache.get("loaded_at") or 0)) > self.ttl_seconds

    def invalidate(self):
        self._cache["loaded_at"] = 0.0

    def _normalize(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _iter_aliases(self, *values: Any) -> Iterable[str]:
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    normalized = self._normalize(item)
                    if normalized:
                        yield normalized
                continue
            normalized = self._normalize(value)
            if normalized:
                yield normalized

    def _register_marketplace(self, integration: dict, config: dict):
        scoped_ids = list(self._iter_aliases(
            config.get("bling_integration_id"),
            config.get("bling_integration_ids"),
        ))
        for shop_id in self._iter_aliases(
            config.get("shop_id"),
            config.get("shop_ids"),
            config.get("bling_loja_id"),
            config.get("bling_loja_ids"),
        ):
            bucket = self._cache["by_shop_id"].setdefault(shop_id, [])
            bucket.append({
                "integration": integration,
                "bling_integration_ids": set(scoped_ids),
            })

    def _register_erp(self, integration: dict, config: dict):
        for company_id in self._iter_aliases(
            config.get("company_id"),
            config.get("company_ids"),
        ):
            self._cache["by_company_id"][company_id] = integration

        cnpj = self._normalize(config.get("cnpj"))
        if cnpj:
            self._cache["by_cnpj"][cnpj] = integration

    def _load_cache(self):
        integrations = supabase_db.table("installed_integrations") \
            .select("id,module_id,instance_name,config,credentials,is_active,access_token,refresh_token") \
            .eq("is_active", True) \
            .execute().data or []

        modules_rows = supabase_db.table("integration_modules") \
            .select("id,slug,tipo,name") \
            .execute().data or []
        modules = {row["id"]: row for row in modules_rows}

        self._cache = {
            "loaded_at": time.time(),
            "by_company_id": {},
            "by_cnpj": {},
            "by_shop_id": {},
            "marketplaces": [],
        }

        for row in integrations:
            module = modules.get(row.get("module_id")) or {}
            tipo = str(module.get("tipo") or "").strip().lower()
            slug = module.get("slug")
            integration = {
                **row,
                "plataforma_slug": slug,
                "module_tipo": tipo,
            }
            config = integration.get("config") or {}

            if slug == "bling" or tipo in {"erp", "aggregator"}:
                self._register_erp(integration, config)

            if tipo == "marketplace":
                self._cache["marketplaces"].append({
                    "id": integration.get("id"),
                    "nome": integration.get("instance_name"),
                    "slug": integration.get("plataforma_slug"),
                    "module_id": integration.get("module_id"),
                    "is_active": integration.get("is_active", True),
                })
                self._register_marketplace(integration, config)

    def _ensure_cache(self):
        if self._cache_expired():
            self._load_cache()

    def get_marketplace_options(self) -> list[dict]:
        self._ensure_cache()
        marketplaces = list(self._cache["marketplaces"])
        marketplaces.sort(key=lambda item: (item.get("nome") or "").lower())
        return marketplaces

    def resolve_bling_by_company_id(self, company_id: str) -> Optional[dict]:
        self._ensure_cache()
        normalized = self._normalize(company_id)
        if not normalized:
            return None
        return self._cache["by_company_id"].get(normalized)

    def resolve_bling_by_cnpj(self, cnpj: str) -> Optional[dict]:
        self._ensure_cache()
        normalized = self._normalize(cnpj)
        if not normalized:
            return None

        direct = self._cache["by_cnpj"].get(normalized)
        if direct:
            return direct

        for known_cnpj, integration in self._cache["by_cnpj"].items():
            if known_cnpj and known_cnpj in normalized:
                return integration
        return None

    def resolve_marketplace_by_shop_id(
        self,
        shop_id: str,
        bling_integration_id: int | None = None,
    ) -> Optional[dict]:
        self._ensure_cache()
        normalized_shop_id = self._normalize(shop_id)
        if not normalized_shop_id:
            return None

        candidates = self._cache["by_shop_id"].get(normalized_shop_id) or []
        if not candidates:
            return None

        if bling_integration_id is not None:
            scoped = [
                candidate for candidate in candidates
                if not candidate["bling_integration_ids"]
                or str(bling_integration_id) in candidate["bling_integration_ids"]
            ]
            if scoped:
                return scoped[0]["integration"]

        return candidates[0]["integration"]


integration_resolution_service = IntegrationResolutionService()
