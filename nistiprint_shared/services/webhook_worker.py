import time
import logging
from datetime import datetime, timedelta
from nistiprint_shared.database.supabase_db_service import supabase_db

# Configurações
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("WebhookWorker")

MAX_RETRIES = 5

class WebhookWorker:
    def __init__(self):
        self.interval_seconds = 5
        self.table = supabase_db.table("webhook_logs")

    def get_pending_webhooks(self):
        """Busca webhooks pendentes ou com erro para processamento."""
        now = datetime.utcnow().isoformat()
        try:
            response = self.table.select("*") \
                .in_("status", ["PENDENTE", "ERRO"]) \
                .lte("next_retry_at", now) \
                .lt("retry_count", MAX_RETRIES) \
                .limit(20) \
                .execute()
            return response.data
        except Exception as e:
            logger.error(f"Erro ao buscar webhooks pendentes: {e}")
            return []

    def process_webhook(self, webhook):
        log_id = webhook["id"]
        platform = webhook["plataforma"]
        payload = webhook.get("payload", {})
        
        logger.info(f"⚙️ Processando webhook {log_id} ({platform})")
        
        try:
            # MARCAR COMO PROCESSANDO
            supabase_db.execute_with_retry(
                self.table.update({
                    "status": "PROCESSANDO",
                    "processing_started_at": datetime.utcnow().isoformat()
                }).eq("id", log_id)
            )

            # --- INTEGRAÇÃO COM LÓGICA DE NEGÓCIO ---
            if platform == 'bling':
                from nistiprint_shared.services.bling_order_processing_service import bling_order_processing_service
                bling_order_processing_service.process_webhook(payload)
            # Adicionar outras plataformas conforme necessário
            # ----------------------------------------
            
            # SUCESSO
            supabase_db.execute_with_retry(
                self.table.update({
                    "status": "SUCESSO",
                    "processed_at": datetime.utcnow().isoformat(),
                    "mensagem_erro": None
                }).eq("id", log_id)
            )
            logger.info(f"✅ Webhook {log_id} processado com sucesso.")

        except Exception as e:
            logger.error(f"❌ Erro ao processar webhook {log_id}: {str(e)}")
            
            retry_count = webhook.get("retry_count", 0) + 1
            wait_seconds = (2 ** retry_count) * 60 # Backoff exponencial
            next_retry = (datetime.utcnow() + timedelta(seconds=wait_seconds)).isoformat()
            
            supabase_db.execute_with_retry(
                self.table.update({
                    "status": "ERRO",
                    "retry_count": retry_count,
                    "next_retry_at": next_retry,
                    "mensagem_erro": str(e)
                }).eq("id", log_id)
            )

    def run(self):
        logger.info("🚀 Webhook Worker iniciado e aguardando eventos...")
        while True:
            webhooks = self.get_pending_webhooks()
            if not webhooks:
                time.sleep(self.interval_seconds)
                continue
                
            for webhook in webhooks:
                self.process_webhook(webhook)
            
            time.sleep(1)

if __name__ == "__main__":
    worker = WebhookWorker()
    worker.run()

