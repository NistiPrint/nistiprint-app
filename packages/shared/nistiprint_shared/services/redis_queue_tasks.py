# ===========================================
# CELERY TASKS - REDIS QUEUE CONSUMER
# ===========================================
# Task simplificada: apenas lÃª do Redis e registra log
# ===========================================

import hashlib
import json
import logging
from datetime import timedelta
from celery import shared_task
import redis
from nistiprint_shared.services.bling_order_processing_service import (
    BlingDetailUnavailableError,
    process_webhook,
)
from nistiprint_shared.services.marketplace_webhook_ingest_service import (
    marketplace_webhook_ingest_service,
)
from nistiprint_shared.services.correlation_service import get_correlation_id, set_correlation_id, generate_correlation_id
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now, get_now_iso, parse_datetime
import uuid

logger = logging.getLogger(__name__)

def log_shared_task_execution(task_type: str = None):
    """
    Decorator para registrar execuÃ§Ã£o de tarefas do shared package em task_execution_logs.
    Similar ao task_logger.py mas adaptado para shared_task.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extrair ou gerar correlation_id
            correlation_id = kwargs.get('correlation_id') or get_correlation_id()
            if not correlation_id:
                correlation_id = str(uuid.uuid4())
            
            # Configurar no contexto
            set_correlation_id(correlation_id)
            
            # Registrar inÃ­cio
            task_log_id = None
            try:
                log_res = supabase_db.table('task_execution_logs').insert({
                    'task_name': func.__name__,
                    'task_type': task_type,
                    'status': 'PROCESSING',
                    'correlation_id': correlation_id,
                    'started_at': get_now_iso(),
                    'metadata': {
                        'args': str(args)[:500],
                        'kwargs': str(kwargs)[:500]
                    }
                }).execute()
                
                task_log_id = log_res.data[0]['id'] if log_res.data else None
            except Exception as e:
                logger.error(f"Erro ao registrar inÃ­cio da tarefa {func.__name__}: {e}")
            
            try:
                # Executar tarefa
                result = func(*args, **kwargs)
                
                # Registrar sucesso
                if task_log_id:
                    try:
                        supabase_db.table('task_execution_logs').update({
                            'status': 'COMPLETED',
                            'finished_at': get_now_iso(),
                            'metadata': {'result': str(result)[:500]}
                        }).eq('id', task_log_id).execute()
                    except Exception as e:
                        logger.error(f"Erro ao registrar sucesso da tarefa {func.__name__}: {e}")
                
                return result
                
            except Exception as e:
                # Registrar falha
                logger.error(f"Erro na execuÃ§Ã£o da tarefa {func.__name__}: {e}")
                if task_log_id:
                    try:
                        supabase_db.table('task_execution_logs').update({
                            'status': 'FAILED',
                            'finished_at': get_now_iso(),
                            'error_message': str(e)[:1000]
                        }).eq('id', task_log_id).execute()
                    except Exception as log_error:
                        logger.error(f"Erro ao registrar falha da tarefa {func.__name__}: {log_error}")
                raise
                
        return wrapper
    return decorator


# ConfiguraÃ§Ã£o do Redis
import os
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

# Filas
BLING_WEBHOOK_QUEUE = 'bling:webhooks:pendentes'
BLING_WEBHOOK_DEAD_LETTER = 'bling:webhooks:dead-letter'
BLING_WEBHOOK_FALHAS = 'bling:webhooks:falhas'
BLING_WEBHOOK_PROCESSADOS = 'bling:webhooks:processados' # Fila para log/histÃ³rico
BLING_WEBHOOK_MAX_RETRIES = int(os.environ.get('BLING_WEBHOOK_MAX_RETRIES', '5'))
MARKETPLACE_WEBHOOK_RETRY_BASE_SECONDS = int(os.environ.get('MARKETPLACE_WEBHOOK_RETRY_BASE_SECONDS', '60'))
MARKETPLACE_WEBHOOK_RETRY_MAX_SECONDS = int(os.environ.get('MARKETPLACE_WEBHOOK_RETRY_MAX_SECONDS', '900'))
MARKETPLACE_WEBHOOK_QUEUE_LOCK_SECONDS = int(os.environ.get('MARKETPLACE_WEBHOOK_QUEUE_LOCK_SECONDS', '300'))
MARKETPLACE_WEBHOOK_RETRY_TTL_DAYS = int(os.environ.get('MARKETPLACE_WEBHOOK_RETRY_TTL_DAYS', '7'))
SHOPEE_WEBHOOK_QUEUE = 'shopee:webhooks:pendentes'
SHOPEE_WEBHOOK_DEAD_LETTER = 'shopee:webhooks:dead-letter'
SHOPEE_WEBHOOK_FALHAS = 'shopee:webhooks:falhas'
MERCADOLIVRE_WEBHOOK_QUEUE = 'mercadolivre:webhooks:pendentes'
MERCADOLIVRE_WEBHOOK_DEAD_LETTER = 'mercadolivre:webhooks:dead-letter'
MERCADOLIVRE_WEBHOOK_FALHAS = 'mercadolivre:webhooks:falhas'

WEBHOOK_QUEUE_BY_SOURCE = {
    'bling': BLING_WEBHOOK_QUEUE,
    'shopee': SHOPEE_WEBHOOK_QUEUE,
    'mercadolivre': MERCADOLIVRE_WEBHOOK_QUEUE,
}

LIVE_QUEUE_ALIASES = {
    'pendentes': BLING_WEBHOOK_QUEUE,
    'falhas': BLING_WEBHOOK_FALHAS,
    'dead_letter': BLING_WEBHOOK_DEAD_LETTER,
    'shopee_pendentes': SHOPEE_WEBHOOK_QUEUE,
    'shopee_falhas': SHOPEE_WEBHOOK_FALHAS,
    'shopee_dead_letter': SHOPEE_WEBHOOK_DEAD_LETTER,
    'mercadolivre_pendentes': MERCADOLIVRE_WEBHOOK_QUEUE,
    'mercadolivre_falhas': MERCADOLIVRE_WEBHOOK_FALHAS,
    'mercadolivre_dead_letter': MERCADOLIVRE_WEBHOOK_DEAD_LETTER,
}

_redis_client = None
MARKETPLACE_PENDING_STATUSES = {
    'pending',
    'processing',
    'pending_retry',
    'retry_scheduled',
    'pending_erp_order',
    'failed',
}
MARKETPLACE_FINAL_STATUSES = {
    'success',
    'skipped',
    'skipped_inactive_source',
    'skipped_stale',
    'manual_intervention',
}

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    return _redis_client

def get_queue_stats():
    """Retorna o tamanho de todas as filas"""
    r = get_redis_client()
    return {
        'pendentes': r.llen(BLING_WEBHOOK_QUEUE),
        'processados': 0,
        'falhas': r.llen(BLING_WEBHOOK_FALHAS),
        'dead_letter': r.llen(BLING_WEBHOOK_DEAD_LETTER),
        'shopee_pendentes': r.llen(SHOPEE_WEBHOOK_QUEUE),
        'shopee_falhas': r.llen(SHOPEE_WEBHOOK_FALHAS),
        'shopee_dead_letter': r.llen(SHOPEE_WEBHOOK_DEAD_LETTER),
        'mercadolivre_pendentes': r.llen(MERCADOLIVRE_WEBHOOK_QUEUE),
        'mercadolivre_falhas': r.llen(MERCADOLIVRE_WEBHOOK_FALHAS),
        'mercadolivre_dead_letter': r.llen(MERCADOLIVRE_WEBHOOK_DEAD_LETTER),
    }

def get_queue_items(queue_name: str, limit: int = 50):
    """Retorna os itens de uma fila especÃ­fica (sem remover)"""
    r = get_redis_client()
    actual_queue = LIVE_QUEUE_ALIASES.get(queue_name)
    
    if not actual_queue:
        return []
        
    items = r.lrange(actual_queue, 0, limit - 1)
    return [json.loads(i) if isinstance(i, str) and (i.startswith('{') or i.startswith('[')) else i for i in items]

def clear_queue(queue_name: str):
    """Limpa uma fila especÃ­fica"""
    r = get_redis_client()
    actual_queue = LIVE_QUEUE_ALIASES.get(queue_name)
    
    if actual_queue:
        return r.delete(actual_queue)
    return 0

def move_items(source: str, destination: str = 'pendentes'):
    """Move todos os itens de uma fila para outra (ex: falhas -> pendentes)."""
    r = get_redis_client()
    source_to_destination = {
        'falhas': BLING_WEBHOOK_QUEUE,
        'dead_letter': BLING_WEBHOOK_QUEUE,
        'shopee_falhas': SHOPEE_WEBHOOK_QUEUE,
        'shopee_dead_letter': SHOPEE_WEBHOOK_QUEUE,
        'mercadolivre_falhas': MERCADOLIVRE_WEBHOOK_QUEUE,
        'mercadolivre_dead_letter': MERCADOLIVRE_WEBHOOK_QUEUE,
    }
    src_queue = LIVE_QUEUE_ALIASES.get(source)
    dest_queue = source_to_destination.get(source) if destination == 'pendentes' else LIVE_QUEUE_ALIASES.get(destination)
    
    if not src_queue or not dest_queue:
        return 0
        
    count = 0
    while True:
        item = r.lpop(src_queue)
        if not item:
            break
        r.rpush(dest_queue, item)
        count += 1
    return count


def _parse_queue_item(item: str) -> dict:
    try:
        parsed = json.loads(item)
        return parsed if isinstance(parsed, dict) else {'raw': parsed}
    except Exception:
        return {'raw_message': item}


def _serialize_queue_item(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _stable_payload_hash(payload: dict) -> str:
    serialized = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _first_present(*values):
    for value in values:
        if value not in (None, ''):
            return value
    return None


def _extract_bling_webhook_identity(data: dict) -> dict:
    body = data.get('data') if isinstance(data.get('data'), dict) else data
    return {
        'body': body,
        'company_id': data.get('companyId') if data.get('companyId') else None,
        'provider_event_id': _first_present(data.get('eventId'), data.get('event_id')),
        'order_id': _first_present(body.get('numeroLoja'), body.get('id')),
        'bling_id': body.get('id'),
        'numero': body.get('numero'),
        'numero_loja': body.get('numeroLoja'),
        'bling_integration_hint': (
            data.get('bling_integration_id')
            or data.get('blingIntegrationId')
            or body.get('bling_integration_id')
        ),
    }


def _extract_shopee_webhook_identity(data: dict) -> dict:
    body = data.get('data') if isinstance(data.get('data'), dict) else data
    orders = body.get('orders') if isinstance(body.get('orders'), list) else []
    return {
        'body': body,
        'company_id': body.get('shop_id') or body.get('shopid') or data.get('shop_id'),
        'provider_event_id': body.get('event_id'),
        'order_id': (
            body.get('order_sn')
            or body.get('ordersn')
            or body.get('order_id')
            or ((orders[0] or {}).get('order_sn') if orders else None)
        ),
    }


def _extract_mercadolivre_webhook_identity(data: dict) -> dict:
    body = data.get('data') if isinstance(data.get('data'), dict) else data
    resource = str(body.get('resource') or body.get('topic') or '')
    order_id = body.get('order_id')
    if not order_id and '/orders/' in resource:
        order_id = resource.rstrip('/').split('/orders/')[-1]
    return {
        'body': body,
        'company_id': body.get('user_id') or body.get('seller_id') or data.get('user_id'),
        'provider_event_id': _first_present(body.get('id'), body.get('_id')),
        'order_id': order_id,
    }


WEBHOOK_IDENTITY_EXTRACTORS = {
    'bling': _extract_bling_webhook_identity,
    'shopee': _extract_shopee_webhook_identity,
    'mercadolivre': _extract_mercadolivre_webhook_identity,
}


def _extract_webhook_identity(source: str, data: dict) -> dict:
    normalized_source = str(source or '').strip().lower()
    extractor = WEBHOOK_IDENTITY_EXTRACTORS.get(normalized_source)
    if not extractor:
        body = data.get('data') if isinstance(data.get('data'), dict) else data
        return {
            'body': body,
            'company_id': None,
            'provider_event_id': None,
            'order_id': None,
        }
    return extractor(data or {})


def _extract_order_context(data: dict):
    identity = _extract_webhook_identity('bling', data)
    order_data = identity.get('body') or {}
    company_id = identity.get('company_id')
    bling_integration_hint = identity.get('bling_integration_hint')
    webhook_event_id = data.get('webhook_event_id')
    bling_id = identity.get('bling_id')
    numero = identity.get('numero')
    numero_loja = identity.get('numero_loja')
    provider_event_id = identity.get('provider_event_id')
    return order_data, company_id, bling_integration_hint, webhook_event_id, bling_id, numero, numero_loja, provider_event_id


def _find_webhook_event_by_provider_event_id(source: str, provider_event_id: str | None) -> dict | None:
    if provider_event_id in (None, ''):
        return None
    try:
        rows = (
            supabase_db.table('webhook_events')
            .select('id,last_status,correlation_id')
            .eq('source', source)
            .eq('provider_event_id', str(provider_event_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    except Exception as e:
        logger.error(
            "Erro ao consultar webhook_events por source=%s provider_event_id=%s: %s",
            source,
            provider_event_id,
            e,
        )
        return None


def _insert_webhook_event(
    raw_payload: dict,
    *,
    source: str = 'bling',
    company_id: str | None,
    bling_id,
    numero_loja,
    correlation_id: str,
    provider_event_id: str | None = None,
    payload_hash: str | None = None,
    retry_expires_at: str | None = None,
) -> int | None:
    try:
        insert_payload = {
            'source': source,
            'company_id': company_id,
            'bling_id': bling_id,
            'numero_loja': str(numero_loja) if numero_loja is not None else None,
            'raw_payload': raw_payload,
            'correlation_id': correlation_id,
            'last_status': 'pending',
            'last_attempt_at': get_now_iso(),
            'attempt_count': 0,
        }
        if provider_event_id not in (None, ''):
            insert_payload['provider_event_id'] = str(provider_event_id)
        if payload_hash:
            insert_payload['payload_hash'] = payload_hash
        if retry_expires_at:
            insert_payload['retry_expires_at'] = retry_expires_at
        response = supabase_db.table('webhook_events').insert(insert_payload).execute()
        return response.data[0]['id'] if response.data else None
    except Exception as e:
        logger.error("Erro ao inserir webhook_events: %s", e)
        return None


def _get_or_create_webhook_event(
    raw_payload: dict,
    *,
    source: str,
    company_id: str | None,
    bling_id,
    numero_loja,
    correlation_id: str,
    provider_event_id: str | None = None,
    payload_hash: str | None = None,
    retry_expires_at: str | None = None,
) -> tuple[int | None, bool, dict | None]:
    existing = _find_webhook_event_by_provider_event_id(source, provider_event_id)
    if existing:
        return existing.get('id'), False, existing

    event_id = _insert_webhook_event(
        raw_payload,
        source=source,
        company_id=company_id,
        bling_id=bling_id,
        numero_loja=numero_loja,
        correlation_id=correlation_id,
        provider_event_id=provider_event_id,
        payload_hash=payload_hash,
        retry_expires_at=retry_expires_at,
    )
    return event_id, True, None


def _extract_marketplace_context(source: str, data: dict):
    identity = _extract_webhook_identity(source, data)
    return (
        identity.get('body') or {},
        identity.get('company_id'),
        identity.get('order_id'),
        identity.get('provider_event_id'),
    )


def enqueue_marketplace_webhook_event(source: str, payload: dict, *, queue_name: str | None = None) -> dict:
    correlation_id = generate_correlation_id()
    _body, company_id, numero_loja, provider_event_id = _extract_marketplace_context(source, payload)
    payload_hash = _stable_payload_hash(payload)
    retry_expires_at = (get_now() + timedelta(days=MARKETPLACE_WEBHOOK_RETRY_TTL_DAYS)).isoformat()
    event_id, created, existing = _get_or_create_webhook_event(
        payload,
        source=source,
        company_id=str(company_id) if company_id not in (None, '') else None,
        bling_id=None,
        numero_loja=str(numero_loja) if numero_loja not in (None, '') else None,
        correlation_id=correlation_id,
        provider_event_id=str(provider_event_id) if provider_event_id not in (None, '') else None,
        payload_hash=payload_hash,
        retry_expires_at=retry_expires_at,
    )
    if event_id and created:
        get_redis_client().rpush(
            queue_name or WEBHOOK_QUEUE_BY_SOURCE[source],
            _serialize_queue_item({'webhook_event_id': event_id}),
        )
    elif event_id and existing:
        logger.info(
            "[webhook-queue] duplicate webhook ignored source=%s provider_event_id=%s existing_event_id=%s status=%s",
            source,
            provider_event_id,
            event_id,
            existing.get('last_status'),
        )
    return {
        'event_id': event_id,
        'correlation_id': correlation_id,
        'company_id': str(company_id) if company_id not in (None, '') else None,
        'numero_loja': str(numero_loja) if numero_loja not in (None, '') else None,
        'provider_event_id': str(provider_event_id) if provider_event_id not in (None, '') else None,
        'queued': bool(event_id and created),
    }


def _update_webhook_event(webhook_event_id: int | None, **fields):
    if not webhook_event_id or not fields:
        return

    try:
        supabase_db.table('webhook_events').update(fields).eq('id', webhook_event_id).execute()
    except Exception as e:
        logger.error("Erro ao atualizar webhook_events id=%s: %s", webhook_event_id, e)


def _increment_webhook_event_attempt(webhook_event_id: int | None):
    if not webhook_event_id:
        return None

    try:
        response = supabase_db.table('webhook_events') \
            .select('attempt_count') \
            .eq('id', webhook_event_id) \
            .single().execute()
        current_attempt_count = int((response.data or {}).get('attempt_count') or 0)
        next_attempt_count = current_attempt_count + 1
        _update_webhook_event(
            webhook_event_id,
            attempt_count=next_attempt_count,
            last_attempt_at=get_now_iso(),
        )
        return next_attempt_count
    except Exception as e:
        logger.error("Erro ao incrementar tentativa em webhook_events id=%s: %s", webhook_event_id, e)
        return None


def _create_webhook_attempt(
    webhook_event_id: int | None,
    *,
    correlation_id: str,
    queue_name: str,
) -> tuple[int | None, int | None]:
    if not webhook_event_id:
        return None, None

    attempt_number = _increment_webhook_event_attempt(webhook_event_id)
    if attempt_number is None:
        attempt_number = 1

    try:
        response = supabase_db.table('webhook_event_attempts').insert({
            'webhook_event_id': webhook_event_id,
            'correlation_id': correlation_id,
            'attempt_number': attempt_number,
            'status': 'processing',
            'queue_name': queue_name,
            'started_at': get_now_iso(),
        }).execute()
        attempt_id = response.data[0]['id'] if response.data else None
    except Exception as e:
        logger.error("Erro ao inserir webhook_event_attempts event_id=%s: %s", webhook_event_id, e)
        attempt_id = None

    return attempt_id, attempt_number


def _finish_webhook_attempt(
    attempt_id: int | None,
    *,
    status: str,
    result_summary: dict | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
):
    if not attempt_id:
        return

    fields = {
        'status': status,
        'finished_at': get_now_iso(),
    }
    if result_summary is not None:
        fields['result_summary'] = result_summary
    if error_type:
        fields['error_type'] = error_type
    if error_message:
        fields['error_message'] = str(error_message)[:4000]

    try:
        supabase_db.table('webhook_event_attempts').update(fields).eq('id', attempt_id).execute()
    except Exception as e:
        logger.error("Erro ao atualizar webhook_event_attempts id=%s: %s", attempt_id, e)


def _mark_failure_payload(data: dict, *, error_type: str, message: str) -> dict:
    failed = dict(data)
    failed['retry_count'] = int(failed.get('retry_count') or 0) + 1
    failed['last_error'] = message[:2000]
    failed['last_error_type'] = error_type
    failed['last_failed_at'] = get_now_iso()
    return failed


def _retry_delay_seconds(retry_count: int) -> int:
    retry_count = max(1, int(retry_count or 1))
    delay = MARKETPLACE_WEBHOOK_RETRY_BASE_SECONDS * (2 ** (retry_count - 1))
    return min(delay, MARKETPLACE_WEBHOOK_RETRY_MAX_SECONDS)


def _acquire_queue_lock(r, queue_name: str) -> tuple[str, str] | tuple[None, None]:
    lock_key = f"{queue_name}:consumer-lock"
    lock_value = str(uuid.uuid4())
    acquired = r.set(lock_key, lock_value, nx=True, ex=MARKETPLACE_WEBHOOK_QUEUE_LOCK_SECONDS)
    return (lock_key, lock_value) if acquired else (None, None)


def _release_queue_lock(r, lock_key: str | None, lock_value: str | None) -> None:
    if not lock_key or not lock_value:
        return
    try:
        r.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            lock_value,
        )
    except Exception as exc:
        logger.warning("Erro ao liberar lock de fila %s: %s", lock_key, exc)


def _move_failure_to_dead_letter(
    r,
    payload: dict,
    reason: str,
    *,
    dead_letter_queue: str = BLING_WEBHOOK_DEAD_LETTER,
    attempt_id: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
):
    dead_letter = dict(payload)
    dead_letter['dead_letter_reason'] = reason
    dead_letter['dead_lettered_at'] = get_now_iso()
    r.rpush(dead_letter_queue, _serialize_queue_item(dead_letter))
    webhook_event_id = dead_letter.get('webhook_event_id')
    if webhook_event_id:
        _update_webhook_event(
            webhook_event_id,
            last_status='dead_letter',
            last_attempt_at=get_now_iso(),
        )
    _finish_webhook_attempt(
        attempt_id,
        status='dead_letter',
        error_type=error_type or dead_letter.get('last_error_type') or 'dead_letter',
        error_message=error_message or dead_letter.get('last_error') or reason,
        result_summary={'dead_letter_reason': reason},
    )


@shared_task(name='nistiprint_shared.services.redis_queue_tasks.drain_bling_webhook_failures')
@log_shared_task_execution(task_type='INTEGRACAO')
def drain_bling_webhook_failures(correlation_id=None):
    """
    Traz falhas de volta para pendentes até o teto de tentativas.

    Esse beat roda em paralelo à renovação de tokens. A ideia é reprocessar
    automaticamente assim que a credencial voltar a funcionar.
    """
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)

    r = get_redis_client()
    moved = 0
    dead_lettered = 0

    while True:
        item = r.lpop(BLING_WEBHOOK_FALHAS)
        if not item:
            break

        data = _parse_queue_item(item)
        retry_count = int(data.get('retry_count') or 0)

        if retry_count >= BLING_WEBHOOK_MAX_RETRIES:
            _move_failure_to_dead_letter(
                r,
                data,
                reason=f"retry_count={retry_count} >= max={BLING_WEBHOOK_MAX_RETRIES}",
            )
            dead_lettered += 1
            continue

        data['requeued_at'] = get_now_iso()
        data['last_queue'] = 'pendentes'
        webhook_event_id = data.get('webhook_event_id')
        if webhook_event_id:
            _update_webhook_event(
                webhook_event_id,
                last_status='pending',
                last_attempt_at=get_now_iso(),
            )
        r.rpush(BLING_WEBHOOK_QUEUE, _serialize_queue_item(data))
        moved += 1

    return {
        'status': 'success',
        'moved': moved,
        'dead_lettered': dead_lettered,
        'max_retries': BLING_WEBHOOK_MAX_RETRIES,
    }


@shared_task(name='nistiprint_shared.services.redis_queue_tasks.consumir_fila_bling')
@log_shared_task_execution(task_type='INTEGRACAO')
def consumir_fila_bling(correlation_id=None):
    """
    Consome a fila de webhooks do Bling no Redis e processa cada um.
    """
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)

    try:
        r = get_redis_client()
        processados = 0

        for _ in range(50):
            mensagem_str = r.lpop(BLING_WEBHOOK_QUEUE)
            if not mensagem_str:
                break

            data = None
            attempt_id = None
            webhook_event_id = None
            try:
                data = _parse_queue_item(mensagem_str)
                logger.info(f"Raw payload recebido do Redis: {mensagem_str[:500]}")

                invalid_queue_item = not data or not isinstance(data, dict)
                if invalid_queue_item:
                    logger.error(f"Payload inválido: não é um dicionário ou está vazio. Payload: {mensagem_str[:200]}")
                    data = {'raw_message': mensagem_str}

                order_data, company_id, bling_integration_hint, webhook_event_id, bling_id, numero, numero_loja, provider_event_id = _extract_order_context(data)
                webhook_correlation_id = generate_correlation_id()

                if not webhook_event_id:
                    webhook_event_id, created_event, existing_event = _get_or_create_webhook_event(
                        data,
                        source='bling',
                        company_id=company_id,
                        bling_id=bling_id,
                        numero_loja=numero_loja,
                        correlation_id=webhook_correlation_id,
                        provider_event_id=str(provider_event_id) if provider_event_id not in (None, '') else None,
                    )
                    if webhook_event_id and created_event:
                        data['webhook_event_id'] = webhook_event_id
                    elif webhook_event_id and existing_event:
                        logger.info(
                            "[webhook-queue] duplicate webhook ignored source=bling provider_event_id=%s existing_event_id=%s status=%s",
                            provider_event_id,
                            webhook_event_id,
                            existing_event.get('last_status'),
                        )
                        continue

                attempt_id, _attempt_number = _create_webhook_attempt(
                    webhook_event_id,
                    correlation_id=webhook_correlation_id,
                    queue_name=BLING_WEBHOOK_QUEUE,
                )
                _update_webhook_event(
                    webhook_event_id,
                    last_status='processing',
                    last_attempt_at=get_now_iso(),
                )

                if invalid_queue_item:
                    failed_payload = _mark_failure_payload(data, error_type='invalid_payload', message='payload vazio ou nao-dict')
                    _move_failure_to_dead_letter(
                        r,
                        failed_payload,
                        reason='invalid_payload',
                        attempt_id=attempt_id,
                        error_type='invalid_payload',
                        error_message='payload vazio ou nao-dict',
                    )
                    continue

                if not bling_id and not numero and not numero_loja:
                    logger.error(f"Payload sem campos obrigatórios (id, numero, numeroLoja). Payload: {mensagem_str[:200]}")
                    _move_failure_to_dead_letter(
                        r,
                        _mark_failure_payload(data, error_type='invalid_payload', message='missing id/numero/numeroLoja'),
                        reason='invalid_payload',
                        attempt_id=attempt_id,
                        error_type='invalid_payload',
                        error_message='missing id/numero/numeroLoja',
                    )
                    continue

                logger.info(f"Iniciando processamento do webhook Bling no worker... (bling_id={bling_id}, numero={numero}, numeroLoja={numero_loja}, companyId={company_id}, blingIntegrationId={bling_integration_hint}, webhook_event_id={webhook_event_id})")
                try:
                    result = process_webhook(
                        order_data,
                        bling_integration_hint=bling_integration_hint,
                        company_id=company_id,
                        correlation_id=webhook_correlation_id,
                        webhook_event_id=webhook_event_id,
                    )
                except BlingDetailUnavailableError as e:
                    result = {
                        'status': 'error',
                        'message': str(e),
                        'error_type': getattr(e, 'error_type', 'bling_detail_unavailable'),
                        'retry_after': getattr(e, 'retry_after', None),
                        'correlation_id': webhook_correlation_id,
                    }

                status_result = result.get('status', 'unknown')
                event_status = result.get('event_status') or status_result
                msg_result = result.get('message', '')
                error_type = result.get('error_type', 'processing_error')

                logger.info(f"Resultado do processamento: {status_result} - {msg_result}")

                if status_result == 'success' or status_result == 'skipped':
                    _finish_webhook_attempt(
                        attempt_id,
                        status=status_result,
                        result_summary=result,
                    )
                    _update_webhook_event(
                        webhook_event_id,
                        last_status=event_status,
                        last_attempt_at=get_now_iso(),
                    )
                    processados += 1
                else:
                    logger.error(f"Falha ao processar webhook: {msg_result}")
                    failed_payload = _mark_failure_payload(data, error_type=error_type, message=msg_result or 'processing_error')
                    failed_payload['correlation_id'] = result.get('correlation_id') or webhook_correlation_id
                    if webhook_event_id:
                        failed_payload['webhook_event_id'] = webhook_event_id
                    retry_count = int(failed_payload.get('retry_count') or 0)
                    if retry_count >= BLING_WEBHOOK_MAX_RETRIES:
                        _move_failure_to_dead_letter(
                            r,
                            failed_payload,
                            reason=f"retry_count={retry_count} >= max={BLING_WEBHOOK_MAX_RETRIES}",
                            attempt_id=attempt_id,
                            error_type=error_type,
                            error_message=msg_result or 'processing_error',
                        )
                    else:
                        _finish_webhook_attempt(
                            attempt_id,
                            status='failed',
                            error_type=error_type,
                            error_message=msg_result or 'processing_error',
                            result_summary=result,
                        )
                        _update_webhook_event(
                            webhook_event_id,
                            last_status='failed',
                            last_attempt_at=get_now_iso(),
                        )
                        r.rpush(BLING_WEBHOOK_FALHAS, _serialize_queue_item(failed_payload))

            except Exception as e:
                logger.error(f"Erro crítico ao processar mensagem do Redis: {str(e)}")
                failed_payload = _mark_failure_payload(data if 'data' in locals() and isinstance(data, dict) else {'raw_message': mensagem_str}, error_type='consumer_exception', message=str(e))
                if webhook_event_id and 'webhook_event_id' not in failed_payload:
                    failed_payload['webhook_event_id'] = webhook_event_id
                _move_failure_to_dead_letter(
                    r,
                    failed_payload,
                    reason='consumer_exception',
                    attempt_id=attempt_id,
                    error_type='consumer_exception',
                    error_message=str(e),
                )

        return {'status': 'success', 'sent': processados}

    except Exception as e:
        logger.error(f"Falha no consumer: {str(e)}")
        return {'status': 'error', 'message': str(e)}


def _drain_marketplace_wake_queue(r, queue_name: str, limit: int = 200) -> int:
    drained = 0
    while drained < limit:
        item = r.lpop(queue_name)
        if not item:
            break
        drained += 1
    return drained


def _marketplace_order_key(event: dict) -> str:
    company_id = str(event.get('company_id') or '').strip()
    numero_loja = str(event.get('numero_loja') or '').strip()
    if not numero_loja:
        return f"event:{event.get('id')}"
    return f"{company_id}:{numero_loja}" if company_id else numero_loja


def _processing_lock_expired(event: dict) -> bool:
    started_at = parse_datetime(event.get('processing_started_at'))
    if not started_at:
        return True
    return started_at <= (get_now() - timedelta(seconds=MARKETPLACE_WEBHOOK_QUEUE_LOCK_SECONDS))


def _event_retry_ready(event: dict) -> bool:
    next_attempt = parse_datetime(event.get('next_attempt_after'))
    return not next_attempt or next_attempt <= get_now()


def _load_next_marketplace_event(source: str, *, limit: int = 500) -> dict | None:
    try:
        rows = (
            supabase_db.table('webhook_events')
            .select('*')
            .eq('source', source)
            .in_('last_status', list(MARKETPLACE_PENDING_STATUSES))
            .order('received_at', desc=False)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        logger.error("Erro ao consultar webhook_events pendentes source=%s: %s", source, exc)
        return None

    first_unresolved_by_order = {}
    for row in rows:
        key = _marketplace_order_key(row)
        first_unresolved_by_order.setdefault(key, row)

    for row in rows:
        key = _marketplace_order_key(row)
        if (first_unresolved_by_order.get(key) or {}).get('id') != row.get('id'):
            continue
        if row.get('last_status') == 'processing' and not _processing_lock_expired(row):
            continue
        if not _event_retry_ready(row):
            continue
        return row
    return None


def _has_pending_marketplace_events(source: str) -> bool:
    try:
        rows = (
            supabase_db.table('webhook_events')
            .select('id')
            .eq('source', source)
            .in_('last_status', list(MARKETPLACE_PENDING_STATUSES))
            .limit(1)
            .execute()
            .data
            or []
        )
        return bool(rows)
    except Exception:
        return False


def _mark_marketplace_processing(webhook_event_id: int, correlation_id: str) -> None:
    _update_webhook_event(
        webhook_event_id,
        last_status='processing',
        processing_started_at=get_now_iso(),
        processing_correlation_id=correlation_id,
        last_attempt_at=get_now_iso(),
    )


def _finalize_marketplace_success(webhook_event_id: int, result: dict, *, order_id: str | None = None) -> None:
    _update_webhook_event(
        webhook_event_id,
        pedido_id=result.get('pedido_id'),
        numero_loja=result.get('external_order_id') or order_id,
        last_status=result.get('event_status') or result.get('status') or 'success',
        next_attempt_after=None,
        processing_started_at=None,
        processing_correlation_id=None,
        last_error_type=None,
        last_error_message=None,
        last_attempt_at=get_now_iso(),
    )


def _schedule_marketplace_retry(
    webhook_event_id: int,
    event: dict,
    *,
    error_type: str,
    message: str,
    pedido_id=None,
    numero_loja=None,
    retry_after: float | None = None,
) -> str:
    now = get_now()
    retry_expires_at = parse_datetime(event.get('retry_expires_at'))
    if retry_expires_at and retry_expires_at <= now:
        final_status = 'manual_intervention'
        next_attempt_after = None
    else:
        final_status = 'pending_retry'
        delay_seconds = retry_after if retry_after is not None else _retry_delay_seconds(event.get('attempt_count') or 1)
        next_attempt_after = (now + timedelta(seconds=max(1, int(delay_seconds)))).isoformat()

    _update_webhook_event(
        webhook_event_id,
        pedido_id=pedido_id,
        numero_loja=numero_loja or event.get('numero_loja'),
        last_status=final_status,
        next_attempt_after=next_attempt_after,
        processing_started_at=None,
        processing_correlation_id=None,
        last_error_type=error_type,
        last_error_message=str(message or error_type)[:4000],
        last_attempt_at=get_now_iso(),
    )
    return final_status


def _consume_marketplace_queue(source: str, queue_name: str, failure_queue: str, dead_letter_queue: str, correlation_id=None):
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)

    r = get_redis_client()
    lock_key, lock_value = _acquire_queue_lock(r, queue_name)
    if not lock_key:
        logger.info("[webhook-queue] source=%s queue=%s ja esta em processamento", source, queue_name)
        return {'status': 'locked', 'sent': 0, 'source': source}

    processados = 0
    blocked = False

    try:
        _drain_marketplace_wake_queue(r, queue_name)

        for _ in range(50):
            event = _load_next_marketplace_event(source)
            if not event:
                blocked = _has_pending_marketplace_events(source)
                break

            webhook_event_id = event.get('id')
            webhook_correlation_id = generate_correlation_id()
            attempt_id = None
            data = event.get('raw_payload') if isinstance(event.get('raw_payload'), dict) else None

            try:
                _mark_marketplace_processing(webhook_event_id, webhook_correlation_id)
                attempt_id, _attempt_number = _create_webhook_attempt(
                    webhook_event_id,
                    correlation_id=webhook_correlation_id,
                    queue_name=queue_name,
                )

                invalid_queue_item = not data or not isinstance(data, dict)
                if invalid_queue_item:
                    final_status = _schedule_marketplace_retry(
                        webhook_event_id,
                        event,
                        error_type='invalid_payload',
                        message='payload vazio ou nao-dict',
                    )
                    _finish_webhook_attempt(
                        attempt_id,
                        status='failed' if final_status != 'manual_intervention' else 'manual_intervention',
                        error_type='invalid_payload',
                        error_message='payload vazio ou nao-dict',
                        result_summary={'retry_mode': 'same_event', 'final_status': final_status},
                    )
                    continue

                body, shop_id, order_id, _provider_event_id = _extract_marketplace_context(source, data)
                logger.info(
                    "[webhook-queue] consuming source=%s webhook_event_id=%s shop_id=%s order_id=%s keys=%s",
                    source,
                    webhook_event_id,
                    shop_id,
                    order_id,
                    sorted(body.keys()) if isinstance(body, dict) else [],
                )

                result = marketplace_webhook_ingest_service.process(
                    source,
                    body,
                    correlation_id=webhook_correlation_id,
                    webhook_event_id=webhook_event_id,
                )
                logger.info(
                    "[webhook-queue] processed source=%s webhook_event_id=%s status=%s pedido_id=%s external_order_id=%s event_status=%s",
                    source,
                    webhook_event_id,
                    result.get('status'),
                    result.get('pedido_id'),
                    result.get('external_order_id'),
                    result.get('event_status'),
                )
                status_result = result.get('status', 'unknown')

                if status_result in ('success', 'skipped'):
                    _finish_webhook_attempt(attempt_id, status=status_result, result_summary=result)
                    _finalize_marketplace_success(
                        webhook_event_id,
                        result,
                        order_id=str(order_id) if order_id not in (None, '') else None,
                    )
                    processados += 1
                    continue

                final_status = _schedule_marketplace_retry(
                    webhook_event_id,
                    event,
                    error_type=result.get('error_type') or result.get('event_status') or 'processing_error',
                    message=result.get('message') or 'processing_error',
                    pedido_id=result.get('pedido_id'),
                    numero_loja=result.get('external_order_id') or (str(order_id) if order_id not in (None, '') else None),
                    retry_after=result.get('retry_after'),
                )
                _finish_webhook_attempt(
                    attempt_id,
                    status='failed' if final_status != 'manual_intervention' else 'manual_intervention',
                    error_type=result.get('error_type') or 'processing_error',
                    error_message=result.get('message') or 'processing_error',
                    result_summary={**result, 'retry_mode': 'same_event', 'final_status': final_status},
                )
            except Exception as e:
                logger.error("Erro critico ao processar webhook %s: %s", source, e, exc_info=True)
                final_status = _schedule_marketplace_retry(
                    webhook_event_id,
                    event,
                    error_type='consumer_exception',
                    message=str(e),
                )
                _finish_webhook_attempt(
                    attempt_id,
                    status='failed' if final_status != 'manual_intervention' else 'manual_intervention',
                    error_type='consumer_exception',
                    error_message=str(e),
                    result_summary={'retry_mode': 'same_event', 'final_status': final_status},
                )
    finally:
        _release_queue_lock(r, lock_key, lock_value)

    return {'status': 'success', 'sent': processados, 'source': source, 'blocked': blocked}

@shared_task(name='nistiprint_shared.services.redis_queue_tasks.consumir_fila_shopee')
@log_shared_task_execution(task_type='INTEGRACAO')
def consumir_fila_shopee(correlation_id=None):
    return _consume_marketplace_queue(
        'shopee',
        SHOPEE_WEBHOOK_QUEUE,
        SHOPEE_WEBHOOK_FALHAS,
        SHOPEE_WEBHOOK_DEAD_LETTER,
        correlation_id=correlation_id,
    )


@shared_task(name='nistiprint_shared.services.redis_queue_tasks.consumir_fila_mercadolivre')
@log_shared_task_execution(task_type='INTEGRACAO')
def consumir_fila_mercadolivre(correlation_id=None):
    return _consume_marketplace_queue(
        'mercadolivre',
        MERCADOLIVRE_WEBHOOK_QUEUE,
        MERCADOLIVRE_WEBHOOK_FALHAS,
        MERCADOLIVRE_WEBHOOK_DEAD_LETTER,
        correlation_id=correlation_id,
    )


@shared_task(name='nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens')
@log_shared_task_execution(task_type='INTEGRACAO')
def sync_firestore_tokens(correlation_id=None):
    """
    Modo de recuperacao: nao sobrescreve automaticamente o Firebase.
    """
    # Configurar correlation_id
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)

    logger.warning(
        "Task sync_firestore_tokens ignorada em modo de recuperacao para nao sobrescrever tokens no Firebase."
    )
    return {
        'status': 'skipped',
        'message': 'Sincronizacao automatica com Firebase desativada; use o sync manual para importar tokens validos.',
    }

