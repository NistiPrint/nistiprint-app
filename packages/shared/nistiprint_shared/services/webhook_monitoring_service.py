import copy
import logging
from typing import Any, Dict, Iterable, List, Optional

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.redis_queue_tasks import (
    BLING_WEBHOOK_QUEUE,
    WEBHOOK_QUEUE_BY_SOURCE,
    _serialize_queue_item,
    get_redis_client,
)
from nistiprint_shared.utils.date_utils import get_now_iso

logger = logging.getLogger(__name__)


SENSITIVE_KEYS = {
    'authorization',
    'access_token',
    'refresh_token',
    'token',
    'secret',
    'signature',
    'x-bling-signature',
    'x-webhook-token',
    'api_key',
    'apikey',
    'password',
}


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = '[REDACTED]'
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ingest_log(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': f"ingest-{row.get('id')}",
        'source': 'pedido_ingest_log',
        'timestamp': row.get('created_at'),
        'stage': row.get('stage'),
        'status': row.get('status'),
        'message': row.get('message'),
        'duration_ms': row.get('duration_ms'),
        'correlation_id': row.get('correlation_id'),
        'raw': row,
    }


def _normalize_task_log(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = row.get('metadata') or {}
    return {
        'id': f"task-{row.get('id')}",
        'source': 'task_execution_logs',
        'timestamp': row.get('started_at') or row.get('created_at') or row.get('finished_at'),
        'stage': row.get('task_name') or row.get('task_type'),
        'status': row.get('status'),
        'message': row.get('error_message') or metadata.get('result') or metadata.get('kwargs'),
        'duration_ms': row.get('duration_ms'),
        'correlation_id': row.get('correlation_id'),
        'raw': row,
    }


def _sort_timestamp(item: Dict[str, Any]) -> str:
    return item.get('timestamp') or item.get('started_at') or item.get('created_at') or ''


class WebhookMonitoringService:
    """
    Consulta e reprocessa webhooks persistidos em webhook_events.
    """

    def __init__(self):
        pass

    def _events_query(self):
        return supabase_db.table('webhook_events').select('*')

    def _attempts_query(self):
        return supabase_db.table('webhook_event_attempts').select('*')

    def _apply_event_filters(self, query, filters: Dict[str, Any]):
        source = filters.get('source')
        if source and source != 'all':
            query = query.eq('source', source)

        if filters.get('status'):
            query = query.eq('last_status', filters['status'])
        if filters.get('bling_id'):
            query = query.eq('bling_id', filters['bling_id'])
        if filters.get('numero_loja'):
            query = query.eq('numero_loja', str(filters['numero_loja']))
        if filters.get('pedido_id'):
            query = query.eq('pedido_id', filters['pedido_id'])
        if filters.get('correlation_id'):
            query = query.eq('correlation_id', filters['correlation_id'])
        if filters.get('since'):
            query = query.gte('received_at', filters['since'])
        if filters.get('until'):
            query = query.lte('received_at', filters['until'])

        return query

    def _public_event(self, row: Dict[str, Any], *, include_payload: bool = False) -> Dict[str, Any]:
        public = dict(row)
        if include_payload:
            public['raw_payload'] = _redact_sensitive(copy.deepcopy(row.get('raw_payload')))
        else:
            public.pop('raw_payload', None)
        return public

    def list_events(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        filters = filters or {}
        page = max(1, _safe_int(filters.get('page'), 1))
        per_page = max(1, min(_safe_int(filters.get('per_page'), 50), 200))
        offset = (page - 1) * per_page

        query = self._apply_event_filters(self._events_query(), filters)
        query = query.order('received_at', desc=True).range(offset, offset + per_page)
        rows = query.execute().data or []

        return {
            'events': [self._public_event(row) for row in rows[:per_page]],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'has_more': len(rows) > per_page,
            },
        }

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        rows = supabase_db.table('webhook_events').select('*').eq('id', event_id).limit(1).execute().data or []
        if not rows:
            return None
        return self._public_event(rows[0], include_payload=True)

    def get_attempts(self, event_id: int) -> List[Dict[str, Any]]:
        return (
            self._attempts_query()
            .eq('webhook_event_id', event_id)
            .order('started_at', desc=True)
            .execute()
            .data
            or []
        )

    def _fetch_logs_for_correlation_ids(self, correlation_ids: Iterable[str]) -> List[Dict[str, Any]]:
        logs: List[Dict[str, Any]] = []
        unique_ids = [cid for cid in dict.fromkeys(correlation_ids) if cid]
        for correlation_id in unique_ids:
            try:
                ingest_rows = (
                    supabase_db.table('pedido_ingest_log')
                    .select('*')
                    .eq('correlation_id', correlation_id)
                    .order('created_at', desc=True)
                    .execute()
                    .data
                    or []
                )
                logs.extend(_normalize_ingest_log(row) for row in ingest_rows)
            except Exception as e:
                logger.warning("Erro ao buscar pedido_ingest_log correlation_id=%s: %s", correlation_id, e)

            try:
                task_rows = (
                    supabase_db.table('task_execution_logs')
                    .select('*')
                    .eq('correlation_id', correlation_id)
                    .order('created_at', desc=True)
                    .execute()
                    .data
                    or []
                )
                logs.extend(_normalize_task_log(row) for row in task_rows)
            except Exception as e:
                logger.warning("Erro ao buscar task_execution_logs correlation_id=%s: %s", correlation_id, e)

        logs.sort(key=_sort_timestamp, reverse=True)
        return logs

    def get_event_logs(self, event_id: int) -> Optional[Dict[str, Any]]:
        event = self.get_event(event_id)
        if not event:
            return None

        attempts = self.get_attempts(event_id)
        correlation_ids = [event.get('correlation_id')] + [row.get('correlation_id') for row in attempts]

        return {
            'event': event,
            'attempts': attempts,
            'logs': self._fetch_logs_for_correlation_ids(correlation_ids),
        }

    def get_processed_count(self) -> int:
        try:
            rows = (
                supabase_db.table('webhook_events')
                .select('id')
                .eq('source', 'bling')
                .in_('last_status', ['success', 'skipped'])
                .execute()
                .data
                or []
            )
            return len(rows)
        except Exception as e:
            logger.warning("Erro ao contar webhooks processados: %s", e)
            return 0

    def list_processed_items(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = (
            supabase_db.table('webhook_events')
            .select('id,source,received_at,last_status,last_attempt_at,attempt_count,pedido_id,bling_id,numero_loja,correlation_id')
            .eq('source', 'bling')
            .in_('last_status', ['success', 'skipped'])
            .order('last_attempt_at', desc=True)
            .limit(max(1, min(int(limit or 20), 100)))
            .execute()
            .data
            or []
        )
        return rows

    def reprocess_event(self, event_id: int) -> Dict[str, Any]:
        rows = supabase_db.table('webhook_events').select('*').eq('id', event_id).limit(1).execute().data or []
        if not rows:
            return {'success': False, 'error': 'Evento de webhook nao encontrado', 'status_code': 404}

        event = rows[0]
        if event.get('last_status') not in ('failed', 'dead_letter', 'manual_intervention', 'pending_retry'):
            return {
                'success': False,
                'error': 'Apenas eventos com status failed, dead_letter, pending_retry ou manual_intervention podem ser reprocessados',
                'status_code': 400,
            }

        raw_payload = event.get('raw_payload')
        if not isinstance(raw_payload, dict) or not raw_payload:
            return {'success': False, 'error': 'Evento sem raw_payload reutilizavel', 'status_code': 400}

        source = event.get('source') or 'bling'
        target_queue = WEBHOOK_QUEUE_BY_SOURCE.get(source, BLING_WEBHOOK_QUEUE)
        if source == 'bling':
            queued_payload = dict(raw_payload)
            queued_payload['webhook_event_id'] = event['id']
            queued_payload['reprocess_requested_at'] = get_now_iso()
            for key in ('last_error', 'last_error_type', 'last_failed_at', 'dead_letter_reason', 'dead_lettered_at'):
                queued_payload.pop(key, None)
        else:
            queued_payload = {
                'webhook_event_id': event['id'],
                'reprocess_requested_at': get_now_iso(),
            }

        get_redis_client().rpush(target_queue, _serialize_queue_item(queued_payload))

        supabase_db.table('webhook_events').update({
            'last_status': 'pending',
            'last_attempt_at': get_now_iso(),
            'next_attempt_after': None,
            'processing_started_at': None,
            'processing_correlation_id': None,
            'last_error_type': None,
            'last_error_message': None,
        }).eq('id', event_id).execute()

        return {
            'success': True,
            'webhook_event_id': event_id,
            'queued': True,
            'queue': target_queue,
        }

webhook_monitoring_service = WebhookMonitoringService()



