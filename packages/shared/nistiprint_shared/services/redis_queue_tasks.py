# ===========================================
# CELERY TASKS - REDIS QUEUE CONSUMER
# ===========================================
# Task simplificada: apenas lê do Redis e registra log
# ===========================================

import json
import logging
from celery import shared_task
import redis
from nistiprint_shared.services.bling_order_processing_service import (
    BlingDetailUnavailableError,
    process_webhook,
)
from nistiprint_shared.services.correlation_service import get_correlation_id, set_correlation_id, generate_correlation_id
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso
import uuid

logger = logging.getLogger(__name__)

def log_shared_task_execution(task_type: str = None):
    """
    Decorator para registrar execução de tarefas do shared package em task_execution_logs.
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
            
            # Registrar início
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
                logger.error(f"Erro ao registrar início da tarefa {func.__name__}: {e}")
            
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
                logger.error(f"Erro na execução da tarefa {func.__name__}: {e}")
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


# Configuração do Redis
import os
REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
REDIS_DB = int(os.environ.get('REDIS_DB', 0))

# Filas
BLING_WEBHOOK_QUEUE = 'bling:webhooks:pendentes'
BLING_WEBHOOK_DEAD_LETTER = 'bling:webhooks:dead-letter'
BLING_WEBHOOK_FALHAS = 'bling:webhooks:falhas'
BLING_WEBHOOK_PROCESSADOS = 'bling:webhooks:processados' # Fila para log/histórico
BLING_WEBHOOK_MAX_RETRIES = int(os.environ.get('BLING_WEBHOOK_MAX_RETRIES', '5'))

_redis_client = None

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
        'processados': r.llen(BLING_WEBHOOK_PROCESSADOS),
        'falhas': r.llen(BLING_WEBHOOK_FALHAS),
        'dead_letter': r.llen(BLING_WEBHOOK_DEAD_LETTER)
    }

def get_queue_items(queue_name: str, limit: int = 50):
    """Retorna os itens de uma fila específica (sem remover)"""
    r = get_redis_client()
    actual_queue = {
        'pendentes': BLING_WEBHOOK_QUEUE,
        'processados': BLING_WEBHOOK_PROCESSADOS,
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(queue_name)
    
    if not actual_queue:
        return []
        
    items = r.lrange(actual_queue, 0, limit - 1)
    return [json.loads(i) if isinstance(i, str) and (i.startswith('{') or i.startswith('[')) else i for i in items]

def clear_queue(queue_name: str):
    """Limpa uma fila específica"""
    r = get_redis_client()
    actual_queue = {
        'pendentes': BLING_WEBHOOK_QUEUE,
        'processados': BLING_WEBHOOK_PROCESSADOS,
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(queue_name)
    
    if actual_queue:
        return r.delete(actual_queue)
    return 0

def move_items(source: str, destination: str = 'pendentes'):
    """Move todos os itens de uma fila para outra (ex: falhas -> pendentes)"""
    r = get_redis_client()
    src_queue = {
        'falhas': BLING_WEBHOOK_FALHAS,
        'dead_letter': BLING_WEBHOOK_DEAD_LETTER
    }.get(source)
    dest_queue = BLING_WEBHOOK_QUEUE if destination == 'pendentes' else None
    
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


def _extract_order_context(data: dict):
    order_data = data.get('data') if data.get('data') and isinstance(data.get('data'), dict) else data
    company_id = data.get('companyId') if data.get('companyId') else None
    bling_integration_hint = (
        data.get('bling_integration_id')
        or data.get('blingIntegrationId')
        or order_data.get('bling_integration_id')
    )
    webhook_event_id = data.get('webhook_event_id')
    bling_id = order_data.get('id')
    numero = order_data.get('numero')
    numero_loja = order_data.get('numeroLoja')
    return order_data, company_id, bling_integration_hint, webhook_event_id, bling_id, numero, numero_loja


def _insert_webhook_event(
    raw_payload: dict,
    *,
    company_id: str | None,
    bling_id,
    numero_loja,
    correlation_id: str,
) -> int | None:
    try:
        response = supabase_db.table('webhook_events').insert({
            'source': 'bling',
            'company_id': company_id,
            'bling_id': bling_id,
            'numero_loja': str(numero_loja) if numero_loja is not None else None,
            'raw_payload': raw_payload,
            'correlation_id': correlation_id,
            'last_status': 'pending',
            'last_attempt_at': get_now_iso(),
            'attempt_count': 1,
        }).execute()
        return response.data[0]['id'] if response.data else None
    except Exception as e:
        logger.error("Erro ao inserir webhook_events: %s", e)
        return None


def _update_webhook_event(webhook_event_id: int | None, **fields):
    if not webhook_event_id or not fields:
        return

    try:
        supabase_db.table('webhook_events').update(fields).eq('id', webhook_event_id).execute()
    except Exception as e:
        logger.error("Erro ao atualizar webhook_events id=%s: %s", webhook_event_id, e)


def _increment_webhook_event_attempt(webhook_event_id: int | None):
    if not webhook_event_id:
        return

    try:
        response = supabase_db.table('webhook_events') \
            .select('attempt_count') \
            .eq('id', webhook_event_id) \
            .single().execute()
        current_attempt_count = int((response.data or {}).get('attempt_count') or 0)
        _update_webhook_event(
            webhook_event_id,
            attempt_count=current_attempt_count + 1,
            last_status='pending',
            last_attempt_at=get_now_iso(),
        )
    except Exception as e:
        logger.error("Erro ao incrementar tentativa em webhook_events id=%s: %s", webhook_event_id, e)


def _mark_failure_payload(data: dict, *, error_type: str, message: str) -> dict:
    failed = dict(data)
    failed['retry_count'] = int(failed.get('retry_count') or 0) + 1
    failed['last_error'] = message[:2000]
    failed['last_error_type'] = error_type
    failed['last_failed_at'] = get_now_iso()
    return failed


def _move_failure_to_dead_letter(r, payload: dict, reason: str):
    dead_letter = dict(payload)
    dead_letter['dead_letter_reason'] = reason
    dead_letter['dead_lettered_at'] = get_now_iso()
    r.rpush(BLING_WEBHOOK_DEAD_LETTER, _serialize_queue_item(dead_letter))


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
            _increment_webhook_event_attempt(webhook_event_id)
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
    # Configurar correlation_id
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        r = get_redis_client()
        processados = 0

        # Consumir fila (máx 50 por ciclo)
        for _ in range(50):
            mensagem_str = r.lpop(BLING_WEBHOOK_QUEUE)
            if not mensagem_str:
                break

            data = None
            try:
                # O payload pode vir direto ou dentro de uma chave 'body' (depende de como o n8n salva)
                data = _parse_queue_item(mensagem_str)
                
                # Log raw payload for debugging
                logger.info(f"Raw payload recebido do Redis: {mensagem_str[:500]}")
                
                # Validate payload has required fields
                if not data or not isinstance(data, dict):
                    logger.error(f"Payload inválido: não é um dicionário ou está vazio. Payload: {mensagem_str[:200]}")
                    r.rpush(BLING_WEBHOOK_DEAD_LETTER, mensagem_str)
                    continue
                
                # Extract order data - Bling webhooks nest the actual order in a 'data' field
                order_data, company_id, bling_integration_hint, webhook_event_id, bling_id, numero, numero_loja = _extract_order_context(data)
                
                # Check for minimum required fields to avoid CNPJ errors
                if not bling_id and not numero and not numero_loja:
                    logger.error(f"Payload sem campos obrigatórios (id, numero, numeroLoja). Payload: {mensagem_str[:200]}")
                    _move_failure_to_dead_letter(
                        r,
                        _mark_failure_payload(data, error_type='invalid_payload', message='missing id/numero/numeroLoja'),
                        reason='invalid_payload',
                    )
                    continue
                
                webhook_correlation_id = generate_correlation_id()
                if not webhook_event_id:
                    webhook_event_id = _insert_webhook_event(
                        data,
                        company_id=company_id,
                        bling_id=bling_id,
                        numero_loja=numero_loja,
                        correlation_id=webhook_correlation_id,
                    )
                    if webhook_event_id:
                        data['webhook_event_id'] = webhook_event_id
                else:
                    _update_webhook_event(
                        webhook_event_id,
                        last_status='pending',
                        last_attempt_at=get_now_iso(),
                    )

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
                        'error_type': 'bling_detail_unavailable',
                        'correlation_id': webhook_correlation_id,
                    }

                status_result = result.get('status', 'unknown')
                msg_result = result.get('message', '')
                error_type = result.get('error_type', 'processing_error')

                logger.info(f"Resultado do processamento: {status_result} - {msg_result}")

                if status_result == 'success' or status_result == 'skipped':
                    # Log de sucesso ou ignorado (filtros) vai para a fila de processados
                    # Adicionamos o resultado ao JSON para o monitor exibir
                    log_data = {
                        'payload': data,
                        'result': result,
                        'processed_at': get_now_iso()
                    }
                    r.rpush(BLING_WEBHOOK_PROCESSADOS, json.dumps(log_data))
                    r.ltrim(BLING_WEBHOOK_PROCESSADOS, -100, -1)
                    processados += 1
                else:
                    # Falha real no processamento (ex: erro de API ou Banco)
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
                        )
                    else:
                        r.rpush(BLING_WEBHOOK_FALHAS, _serialize_queue_item(failed_payload))

            except Exception as e:
                logger.error(f"Erro crítico ao processar mensagem do Redis: {str(e)}")
                failed_payload = _mark_failure_payload(data if 'data' in locals() and isinstance(data, dict) else {'raw_message': mensagem_str}, error_type='consumer_exception', message=str(e))
                _move_failure_to_dead_letter(r, failed_payload, reason='consumer_exception')

        return {'status': 'success', 'sent': processados}

    except Exception as e:
        logger.error(f"Falha no consumer: {str(e)}")
        return {'status': 'error', 'message': str(e)}

@shared_task(name='nistiprint_shared.services.redis_queue_tasks.sync_firestore_tokens')
@log_shared_task_execution(task_type='INTEGRACAO')
def sync_firestore_tokens(correlation_id=None):
    """
    Sincroniza tokens do Bling do Firestore para o Supabase.
    """
    # Configurar correlation_id
    correlation_id = correlation_id or get_correlation_id()
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    set_correlation_id(correlation_id)
    
    try:
        from nistiprint_shared.services.token_manager.sync_firestore import sync_bling_to_supabase
        logger.info("Iniciando task agendada de sincronização com Firestore...")
        success = sync_bling_to_supabase()
        return {'status': 'success' if success else 'error'}
    except Exception as e:
        logger.error(f"Erro na task sync_firestore_tokens: {str(e)}")
        return {'status': 'error', 'message': str(e)}
