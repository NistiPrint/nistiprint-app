import logging
import os
from sqlalchemy import create_engine
from nistiprint_shared.database.database import db

logger = logging.getLogger(__name__)

class LegacySyncService:
    """
    Service for providing connection to Legacy MySQL database.
    (Sync functionality removed as per user request for direct read coexistence).
    """
    @staticmethod
    def _get_legacy_connection():
        """
        Obtém uma conexão com o MySQL legado.
        Tenta via Bind 'legacy_mysql' ou via DATABASE_URL direta.
        """
        legacy_url = os.environ.get('DATABASE_URL')
        if not legacy_url:
            raise Exception("Variável DATABASE_URL não configurada para conexão legada.")
            
        try:
            # Tenta via Bind se existir
            return db.get_engine(bind='legacy_mysql').connect()
        except Exception:
            # Fallback para engine direta
            logger.info("Criando engine direta para MySQL Legado via DATABASE_URL.")
            engine = create_engine(legacy_url)
            return engine.connect()

