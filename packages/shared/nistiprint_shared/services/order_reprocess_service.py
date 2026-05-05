import logging
from typing import Any, Dict, List, Optional

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_service import order_service
from nistiprint_shared.services.redis_queue_tasks import (
    BLING_WEBHOOK_QUEUE,
    _serialize_queue_item,
    get_redis_client,
)
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)


class OrderReprocessService:
    """
    Reprocessa pedidos reenfileirando o payload original do webhook.
    """

    def __init__(self):
        self.pedidos_table = supabase_db.table('pedidos')
        self.webhook_events_table = supabase_db.table('webhook_events')

    def _get_pedido(self, pedido_id: int) -> Optional[Dict[str, Any]]:
        response = self.pedidos_table.select("*").eq('id', pedido_id).single().execute()
        return response.data or None

    def _get_bling_context(self, pedido: Dict[str, Any]) -> Dict[str, Any]:
        pedido_bling_id = pedido.get('pedido_bling_id')
        if not pedido_bling_id:
            return {'bling_id': None, 'numero_loja': pedido.get('codigo_pedido_externo')}

        try:
            response = supabase_db.table('pedidos_bling') \
                .select('bling_id, numero_loja') \
                .eq('id', pedido_bling_id) \
                .single().execute()
            row = response.data or {}
            return {
                'bling_id': row.get('bling_id'),
                'numero_loja': row.get('numero_loja') or pedido.get('codigo_pedido_externo'),
            }
        except Exception as e:
            logger.warning("Erro ao buscar contexto Bling do pedido %s: %s", pedido.get('id'), e)
            return {'bling_id': None, 'numero_loja': pedido.get('codigo_pedido_externo')}

    def _get_latest_webhook_event(self, pedido_id: int, pedido: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        try:
            rows = self.webhook_events_table.select('*') \
                .eq('pedido_id', pedido_id) \
                .order('received_at', desc=True) \
                .limit(5).execute().data or []
            candidates.extend(rows)
        except Exception as e:
            logger.warning("Erro ao buscar webhook_events por pedido_id=%s: %s", pedido_id, e)

        context = self._get_bling_context(pedido)

        if context.get('bling_id'):
            try:
                rows = self.webhook_events_table.select('*') \
                    .eq('bling_id', context['bling_id']) \
                    .order('received_at', desc=True) \
                    .limit(5).execute().data or []
                candidates.extend(rows)
            except Exception as e:
                logger.warning("Erro ao buscar webhook_events por bling_id=%s: %s", context['bling_id'], e)

        if context.get('numero_loja'):
            try:
                rows = self.webhook_events_table.select('*') \
                    .eq('numero_loja', str(context['numero_loja'])) \
                    .order('received_at', desc=True) \
                    .limit(5).execute().data or []
                candidates.extend(rows)
            except Exception as e:
                logger.warning("Erro ao buscar webhook_events por numero_loja=%s: %s", context['numero_loja'], e)

        if not candidates:
            return None

        unique_candidates = {}
        for row in candidates:
            if row and row.get('id') is not None:
                unique_candidates[row['id']] = row

        return sorted(
            unique_candidates.values(),
            key=lambda row: row.get('received_at') or row.get('created_at') or '',
            reverse=True,
        )[0]

    def _queue_webhook_event(self, webhook_event: Dict[str, Any]) -> None:
        raw_payload = webhook_event.get('raw_payload')
        if not isinstance(raw_payload, dict) or not raw_payload:
            raise ValueError("webhook_event sem raw_payload reutilizavel")

        queued_payload = dict(raw_payload)
        queued_payload['webhook_event_id'] = webhook_event['id']
        queued_payload['reprocess_requested_at'] = get_now_iso()

        get_redis_client().rpush(BLING_WEBHOOK_QUEUE, _serialize_queue_item(queued_payload))

    def reprocess_order(self, pedido_id: int, integration_id: Optional[int] = None) -> Dict[str, Any]:
        try:
            pedido = self._get_pedido(pedido_id)
            if not pedido:
                return {"success": False, "error": "Pedido nao encontrado", "pedido_id": pedido_id}

            webhook_event = self._get_latest_webhook_event(pedido_id, pedido)
            if not webhook_event:
                return {
                    "success": False,
                    "error": "Nenhum webhook original encontrado para este pedido",
                    "pedido_id": pedido_id,
                }

            self._queue_webhook_event(webhook_event)

            next_attempt_count = int(webhook_event.get('attempt_count') or 0) + 1
            self.webhook_events_table.update({
                'last_status': 'pending',
                'last_attempt_at': get_now_iso(),
                'attempt_count': next_attempt_count,
            }).eq('id', webhook_event['id']).execute()

            order_service.register_event(
                pedido_id=pedido_id,
                tipo='ORDER_REPROCESSED',
                descricao='Pedido reenfileirado com payload original do webhook',
                payload={
                    'integration_id': integration_id,
                    'webhook_event_id': webhook_event['id'],
                    'attempt_count': next_attempt_count,
                },
            )

            return {
                "success": True,
                "pedido_id": pedido_id,
                "codigo_pedido_externo": pedido.get('codigo_pedido_externo'),
                "webhook_event_id": webhook_event['id'],
                "attempt_count": next_attempt_count,
                "queued": True,
            }
        except Exception as e:
            logger.error("Erro ao reprocessar pedido %s: %s", pedido_id, e, exc_info=True)
            return {"success": False, "error": str(e), "pedido_id": pedido_id}

    def reprocess_batch(self, pedido_ids: List[int], integration_id: Optional[int] = None) -> Dict[str, Any]:
        results = []
        errors = []

        for pedido_id in pedido_ids:
            result = self.reprocess_order(pedido_id, integration_id)
            if result.get('success'):
                results.append(result)
            else:
                errors.append(result)

        return {
            "success": True,
            "total_requested": len(pedido_ids),
            "total_processed": len(results),
            "total_errors": len(errors),
            "results": results,
            "errors": errors,
        }

    def reprocess_by_canal(
        self,
        canal_venda_id: int,
        date_range: Optional[Dict[str, str]] = None,
        integration_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            query = self.pedidos_table.select("id").eq('canal_venda_id', canal_venda_id)

            if date_range:
                start_date = date_range.get('start_date')
                end_date = date_range.get('end_date')

                if start_date:
                    query = query.gte('data_venda', start_date)
                if end_date:
                    query = query.lte('data_venda', end_date)

            response = query.execute()
            pedido_ids = [row['id'] for row in (response.data or []) if row.get('id')]

            if not pedido_ids:
                return {
                    "success": True,
                    "message": "Nenhum pedido encontrado para os criterios especificados",
                    "total_requested": 0,
                    "total_processed": 0,
                    "results": [],
                    "errors": [],
                }

            if len(pedido_ids) > 100:
                logger.warning("Limitando reprocessamento por canal a 100 pedidos (encontrados %s)", len(pedido_ids))
                pedido_ids = pedido_ids[:100]

            return self.reprocess_batch(pedido_ids, integration_id)
        except Exception as e:
            logger.error("Erro ao reprocessar pedidos do canal %s: %s", canal_venda_id, e, exc_info=True)
            return {"success": False, "error": str(e), "canal_venda_id": canal_venda_id}


order_reprocess_service = OrderReprocessService()
