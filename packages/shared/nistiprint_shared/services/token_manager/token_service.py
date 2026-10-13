import time
import logging
from typing import List
from nistiprint_shared.database.supabase_db_service import supabase_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TokenManager")

class TokenManager:
    def __init__(self):
        self.interval_hours = 4

    def get_integrations_to_refresh(self) -> List[dict]:
        """Busca todas as integrações ativas."""
        response = supabase_db.table("installed_integrations") \
            .select("*") \
            .eq("is_active", True) \
            .execute()
        return response.data

    def _process_refresh(self, integration):
        module_id = integration.get("module_id", "").lower()
        integration_id = integration.get("id")
        if not integration_id:
            logger.warning("Integração sem ID; renovação ignorada")
            return

        try:
            from nistiprint_shared.services.installed_integration_service import (
                installed_integration_service,
            )

            installed_integration_service.renew_integration_token(
                str(integration_id), execution_mode="token_manager_legacy"
            )
            logger.info(
                "Sucesso ao renovar token de %s (ID: %s)", module_id, integration_id
            )

        except Exception as e:
            logger.error(
                "Falha ao processar %s (ID: %s): %s",
                module_id, integration_id, e,
            )

    def refresh_all(self):
        logger.info("Iniciando ciclo de renovação...")
        integrations = self.get_integrations_to_refresh()
        for integration in integrations:
            self._process_refresh(integration)

    def run(self):
        while True:
            self.refresh_all()
            logger.info(f"Ciclo finalizado. Próxima execução em {self.interval_hours} horas.")
            time.sleep(self.interval_hours * 3600)

if __name__ == "__main__":
    manager = TokenManager()
    manager.run()

