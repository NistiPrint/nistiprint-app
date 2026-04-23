import importlib
import logging
from typing import List, Dict, Optional
from nistiprint_shared.services.installed_integration_service import installed_integration_service

logger = logging.getLogger("PlatformApiService")

class PlatformApiService:
    """
    Generic service to call platform-specific APIs using drivers.
    
    Drivers disponíveis:
    - shopee: API Shopee (get_order_detail, get_orders_list)
    - mercadolivre: API Mercado Livre
    - amazon: API Amazon
    - shein: API Shein
    - tiktok: API TikTok
    
    Nota: Bling NÃO usa driver, é acessado via BlingClient diretamente.
    """

    def __init__(self):
        # Map module IDs to their respective drivers
        # Apenas plataformas com drivers em platform_drivers/
        self.drivers = {
            "shopee": "nistiprint_shared.services.platform_drivers.shopee",
            "mercadolivre": "nistiprint_shared.services.platform_drivers.mercadolivre",
            "amazon": "nistiprint_shared.services.platform_drivers.amazon",
            "shein": "nistiprint_shared.services.platform_drivers.shein",
            "tiktok": "nistiprint_shared.services.platform_drivers.tiktok"
        }

    def _get_driver(self, module_id: str):
        """Dynamic import of the platform driver"""
        driver_path = self.drivers.get(module_id)
        if not driver_path:
            # Try to see if it's a variant (e.g. shopeeflex -> shopee)
            for key in self.drivers:
                if key in module_id:
                    driver_path = self.drivers[key]
                    break

        if not driver_path:
            # Mensagem mais clara sobre módulos suportados
            supported = ', '.join(self.drivers.keys())
            logger.warning(f"Módulo '{module_id}' não tem driver. Suportados: {supported}")
            return None

        try:
            return importlib.import_module(driver_path)
        except ImportError as e:
            logger.error(f"Could not import driver {driver_path}: {e}")
            return None

    def get_order_detail(self, order_sn_list: List[str], instance_id: Optional[str] = None, module_id: Optional[str] = "shopee") -> Dict:
        """
        Generic method to fetch order details from any platform.
        """
        return self.get_entity_detail("order", order_sn_list, instance_id, module_id)

    def get_orders_list(self, instance_id: Optional[str] = None, module_id: Optional[str] = "shopee", filters: Optional[Dict] = None) -> List[Dict]:
        """
        Generic method to fetch list of orders from any platform.
        """
        # 1. Get Integration
        integration = None
        if instance_id:
            integration_obj = installed_integration_service.get_installed_by_id(instance_id)
            if integration_obj:
                integration = integration_obj.to_dict()
                integration['id'] = instance_id
                module_id = integration_obj.module_id
        else:
            # Find first active integration for the given module_id
            active_integrations = installed_integration_service.get_installed_by_module(module_id)
            if active_integrations:
                integration = active_integrations[0].to_dict()
                integration['id'] = active_integrations[0].id
                module_id = active_integrations[0].module_id

        if not integration:
            return [{"error": f"Nenhuma integração ativa encontrada para o módulo '{module_id}'."}]

        # 2. Get Driver
        driver = self._get_driver(module_id)
        method_name = "get_orders_list"

        if not driver or not hasattr(driver, method_name):
            return [{"error": f"O módulo '{module_id}' não suporta listagem de pedidos em tempo real."}]

        # 3. Call Driver
        try:
            method = getattr(driver, method_name)
            return method(integration, filters)
        except Exception as e:
            logger.error(f"Error calling driver for {module_id} (orders list): {e}")
            return [{"error": str(e)}]

    def get_entity_detail(self, entity_type: str, entity_ids: List[str], instance_id: Optional[str] = None, module_id: Optional[str] = "shopee") -> Dict:
        """
        Generic method to fetch any entity details from any platform.
        """
        # 1. Get Integration
        integration = None
        if instance_id:
            integration_obj = installed_integration_service.get_installed_by_id(instance_id)
            if integration_obj:
                integration = integration_obj.to_dict()
                integration['id'] = instance_id
                module_id = integration_obj.module_id
        else:
            # Find first active integration for the given module_id
            active_integrations = installed_integration_service.get_installed_by_module(module_id)
            if active_integrations:
                integration = active_integrations[0].to_dict()
                integration['id'] = active_integrations[0].id
                module_id = active_integrations[0].module_id

        if not integration:
            return {"error": f"Nenhuma integração ativa encontrada para o módulo '{module_id}'."}

        # 2. Get Driver
        driver = self._get_driver(module_id)
        method_name = f"get_{entity_type}_detail"

        if not driver or not hasattr(driver, method_name):
            return {"error": f"O módulo '{module_id}' não suporta consulta em tempo real de {entity_type}s."}

        # 3. Call Driver
        try:
            method = getattr(driver, method_name)
            return method(integration, entity_ids)
        except Exception as e:
            logger.error(f"Error calling driver for {module_id} ({entity_type}): {e}")
            return {"error": str(e)}

platform_api_service = PlatformApiService()

