import importlib
import logging
from typing import Dict, List, Optional

from nistiprint_shared.services.credential_resolver_service import (
    credential_resolver_service,
)
from nistiprint_shared.services.installed_integration_service import (
    installed_integration_service,
)

logger = logging.getLogger("PlatformApiService")


class PlatformApiService:
    """
    Generic service to call platform-specific APIs using drivers.
    """

    def __init__(self):
        self.drivers = {
            "shopee": "nistiprint_shared.services.platform_drivers.shopee",
            "mercadolivre": "nistiprint_shared.services.platform_drivers.mercadolivre",
            "amazon": "nistiprint_shared.services.platform_drivers.amazon",
            "amazonfba_classic": "nistiprint_shared.services.platform_drivers.amazon",
            "amazon_fulfillment": "nistiprint_shared.services.platform_drivers.amazon_fulfillment",
            "shein": "nistiprint_shared.services.platform_drivers.shein",
            "tiktok": "nistiprint_shared.services.platform_drivers.tiktok",
            "tiktokshop": "nistiprint_shared.services.platform_drivers.tiktok",
            "kwai": "nistiprint_shared.services.platform_drivers.kwai",
            "lojaintegrada": "nistiprint_shared.services.platform_drivers.lojaintegrada",
        }

    def _get_driver(self, module_id: str):
        driver_path = self.drivers.get(module_id)
        if not driver_path:
            for key in self.drivers:
                if key in module_id:
                    driver_path = self.drivers[key]
                    break

        if not driver_path:
            supported = ", ".join(self.drivers.keys())
            logger.warning(
                "Modulo '%s' nao tem driver. Suportados: %s", module_id, supported
            )
            return None

        try:
            return importlib.import_module(driver_path)
        except ImportError as exc:
            logger.error("Could not import driver %s: %s", driver_path, exc)
            return None

    def _resolve_integration(
        self, instance_id: Optional[str], module_id: Optional[str]
    ) -> tuple[dict | None, str]:
        integration = None
        resolved_module_id = module_id or "shopee"
        if instance_id:
            integration_obj = installed_integration_service.get_installed_by_id(instance_id)
            if integration_obj:
                integration = integration_obj.to_dict()
                integration["id"] = instance_id
                resolved_module_id = integration_obj.module_id
        else:
            active_integrations = installed_integration_service.get_installed_by_module(
                resolved_module_id
            )
            if active_integrations:
                integration = active_integrations[0].to_dict()
                integration["id"] = active_integrations[0].id
                resolved_module_id = active_integrations[0].module_id

        if integration:
            integration = credential_resolver_service.hydrate_integration(integration)
        return integration, resolved_module_id

    def get_order_detail(
        self,
        order_sn_list: List[str],
        instance_id: Optional[str] = None,
        module_id: Optional[str] = "shopee",
    ) -> Dict:
        return self.get_entity_detail("order", order_sn_list, instance_id, module_id)

    def get_orders_list(
        self,
        instance_id: Optional[str] = None,
        module_id: Optional[str] = "shopee",
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        integration, resolved_module_id = self._resolve_integration(instance_id, module_id)
        if not integration:
            return [
                {
                    "error": (
                        f"Nenhuma integracao ativa encontrada para o modulo "
                        f"'{resolved_module_id}'."
                    )
                }
            ]

        driver = self._get_driver(resolved_module_id)
        method_name = "get_orders_list"

        if not driver or not hasattr(driver, method_name):
            return [
                {
                    "error": (
                        f"O modulo '{resolved_module_id}' nao suporta listagem de "
                        "pedidos em tempo real."
                    )
                }
            ]

        try:
            method = getattr(driver, method_name)
            return method(integration, filters)
        except Exception as exc:
            logger.error(
                "Error calling driver for %s (orders list): %s",
                resolved_module_id,
                exc,
            )
            return [{"error": str(exc)}]

    def get_entity_detail(
        self,
        entity_type: str,
        entity_ids: List[str],
        instance_id: Optional[str] = None,
        module_id: Optional[str] = "shopee",
    ) -> Dict:
        integration, resolved_module_id = self._resolve_integration(instance_id, module_id)
        if not integration:
            return {
                "error": (
                    f"Nenhuma integracao ativa encontrada para o modulo "
                    f"'{resolved_module_id}'."
                )
            }

        driver = self._get_driver(resolved_module_id)
        method_name = f"get_{entity_type}_detail"

        if not driver or not hasattr(driver, method_name):
            return {
                "error": (
                    f"O modulo '{resolved_module_id}' nao suporta consulta em "
                    f"tempo real de {entity_type}s."
                )
            }

        try:
            method = getattr(driver, method_name)
            return method(integration, entity_ids)
        except Exception as exc:
            logger.error(
                "Error calling driver for %s (%s): %s",
                resolved_module_id,
                entity_type,
                exc,
            )
            return {"error": str(exc)}

    def test_connection(
        self,
        integration: Dict,
        module_id: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Dict:
        resolved_module_id = module_id or integration.get("module_id")
        hydrated = credential_resolver_service.hydrate_integration(integration)
        driver = self._get_driver(resolved_module_id)
        if not driver or not hasattr(driver, "test_connection"):
            return {
                "error": (
                    f"O modulo '{resolved_module_id}' nao suporta teste de conexao "
                    "via driver."
                )
            }

        try:
            return driver.test_connection(hydrated, path=path)
        except Exception as exc:
            logger.error(
                "Error testing driver connection for %s: %s",
                resolved_module_id,
                exc,
            )
            return {"error": str(exc)}


platform_api_service = PlatformApiService()
