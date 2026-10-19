"""Refresh asynchronous read models used by dispatch and personalization screens."""

from celery_config import celery_app
import logging
from time import perf_counter
from nistiprint_shared.database.supabase_db_service import supabase_db

logger = logging.getLogger(__name__)

@celery_app.task(name="tasks.operational_read_model_tasks.refresh_operational_read_models")
def refresh_operational_read_models(limit=100):
    """Process transactional outbox events and a bounded initial backfill."""
    started = perf_counter()
    result = supabase_db.rpc("refresh_operational_read_models", {"p_limit": limit}).execute()
    data = result.data
    if isinstance(data, list) and data:
        data = data[0]
    data = data or {"processed": 0, "orders": 0}
    logger.info(
        "operational_read_models duration_ms=%.1f processed=%s orders=%s backfill_pending=%s",
        (perf_counter() - started) * 1000,
        data.get("processed"), data.get("orders"), data.get("backfill_pending"),
    )
    return data
