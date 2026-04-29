"""Reprocessa pedidos sem marketplace_integration_id usando process_webhook."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv()

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.bling_order_processing_service import process_webhook
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_marketplace")

def main():
    """Reprocessa pedidos órfãos sem marketplace_integration_id."""
    logger.info("Iniciando backfill de pedidos sem marketplace_integration_id...")
    
    # Buscar pedidos órfãos
    orfaos = supabase_db.table('pedidos').select('id, pedido_bling_id, bling_integration_id') \
        .is_('marketplace_integration_id', 'null').eq('origem', 'BLING').execute().data or []
    
    logger.info(f"Encontrados {len(orfaos)} pedidos órfãos para reprocessar")
    
    sucesso = 0
    falha = 0
    
    for p in orfaos:
        logger.info(f"Processando pedido {p['id']}...")
        
        # Buscar payload original em pedidos_bling
        pb = supabase_db.table('pedidos_bling').select('raw_payload, bling_integration_id') \
            .eq('id', p['pedido_bling_id']).single().execute().data
        
        if not pb or not pb.get('raw_payload'):
            logger.warning(f"Pedido {p['id']}: sem payload em pedidos_bling, pulando")
            falha += 1
            continue
        
        try:
            process_webhook(pb['raw_payload'], bling_integration_hint=pb.get('bling_integration_id'))
            logger.info(f"Pedido {p['id']}: reprocessado com sucesso")
            sucesso += 1
        except Exception as e:
            logger.error(f"Pedido {p['id']}: falha ao reprocessar - {e}")
            falha += 1
    
    logger.info(f"Backfill concluído: {sucesso} sucessos, {falha} falhas")

if __name__ == "__main__":
    main()
