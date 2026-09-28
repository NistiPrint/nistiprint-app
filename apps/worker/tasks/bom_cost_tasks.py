"""Background propagation of product costs through BOM parent chains."""

from celery_config import celery_app
from nistiprint_shared.services.product_service import product_service


@celery_app.task(
    bind=True,
    name='tasks.bom_cost_tasks.propagate_composite_cost_to_parents',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def propagate_composite_cost_to_parents(self, product_id: str):
    product_service.propagate_composite_cost_to_parents(str(product_id))
