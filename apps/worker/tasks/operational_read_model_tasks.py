"""Refresh asynchronous read models used by dispatch and personalization screens."""

from celery_config import celery_app
from nistiprint_shared.database.supabase_db_service import supabase_db


@celery_app.task(name="tasks.operational_read_model_tasks.refresh_operational_read_models")
def refresh_operational_read_models(limit=100):
    """Process transactional outbox events and a bounded initial backfill."""
    result = supabase_db.rpc("refresh_operational_read_models", {"p_limit": limit}).execute()
    data = result.data
    if isinstance(data, list) and data:
        return data[0]
    return data or {"processed": 0, "orders": 0}
