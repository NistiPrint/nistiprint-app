import os
import time
import logging
import importlib
from datetime import datetime
from typing import List
from supabase import create_client, Client

# Configurações básicas
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TokenManager")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE_URL e SUPABASE_KEY devem ser configuradas.")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class TokenManager:
    def __init__(self):
        self.interval_hours = 4
        # Mapeamento de module_id para drivers na pasta drivers/
        self.drivers = {
            "bling": "services.token_manager.drivers.bling",
            "shopee": "services.token_manager.drivers.shopee",
        }

    def get_integrations_to_refresh(self) -> List[dict]:
        """Busca todas as integrações ativas."""
        response = supabase.table("installed_integrations") \
            .select("*") \
            .eq("is_active", True) \
            .execute()
        return response.data

    def _process_refresh(self, integration):
        module_id = integration.get("module_id", "").lower()
        
        # Encontra o driver correto
        driver_path = self.drivers.get(module_id)
        if not driver_path:
            logger.warning(f"Nenhum driver encontrado para o módulo: {module_id}")
            return

        try:
            # Import dinâmico do driver
            module = importlib.import_module(driver_path)
            # Executa a função refresh_token do driver
            update_data = module.refresh_token(integration)
            
            # Persiste no Supabase
            if update_data:
                update_data["last_refresh_attempt"] = datetime.utcnow().isoformat()
                update_data["refresh_error"] = None
                
                supabase.table("installed_integrations") \
                    .update(update_data) \
                    .eq("id", integration["id"]) \
                    .execute()
                
                logger.info(f"Sucesso ao renovar token de {module_id} (ID: {integration['id']})")

        except Exception as e:
            logger.error(f"Falha ao processar {module_id}: {str(e)}")
            supabase.table("installed_integrations").update({
                "last_refresh_attempt": datetime.utcnow().isoformat(),
                "refresh_error": str(e)
            }).eq("id", integration["id"]).execute()

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

