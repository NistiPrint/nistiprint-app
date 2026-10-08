"""
Task Management API Endpoints
Provides endpoints for monitoring and managing async task execution logs
"""
from datetime import datetime
from flask import Blueprint, request, jsonify
from routes.auth import admin_required, check_permission
from nistiprint_shared.database.supabase_db_service import supabase_db
from routes.task_center_api import _sanitize

tasks_api_bp = Blueprint('tasks_api', __name__, url_prefix='/api/v2/tasks')
admin_worker_logs_bp = Blueprint('admin_worker_logs', __name__)


def _parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    return None


def _sort_key(item):
    for key in ('created_at', 'started_at', 'finished_at', 'last_failed_at'):
        dt = _parse_iso_datetime(item.get(key))
        if dt:
            return dt
    return datetime.min


def _normalize_ingest_log(row):
    payload_summary = row.get('payload_summary') or {}
    return {
        'id': f"ingest-{row.get('id')}",
        'source': 'pedido_ingest_log',
        'entity': 'pedido',
        'timestamp': row.get('created_at'),
        'stage': row.get('stage'),
        'status': row.get('status'),
        'message': row.get('message'),
        'duration_ms': row.get('duration_ms'),
        'correlation_id': row.get('correlation_id'),
        'bling_integration_id': row.get('bling_integration_id'),
        'numero_loja': row.get('numero_loja'),
        'pedido_id': row.get('pedido_id'),
        'bling_id': row.get('bling_id'),
        'payload_summary': payload_summary,
        'raw': row,
    }


def _normalize_task_log(row):
    metadata = row.get('metadata') or {}
    return {
        'id': f"task-{row.get('id')}",
        'source': 'task_execution_logs',
        'entity': 'task',
        'timestamp': row.get('started_at') or row.get('created_at') or row.get('finished_at'),
        'stage': row.get('task_name') or row.get('task_type'),
        'status': row.get('status'),
        'message': row.get('error_message') or metadata.get('result') or metadata.get('kwargs'),
        'duration_ms': row.get('duration_ms'),
        'correlation_id': row.get('correlation_id'),
        'task_name': row.get('task_name'),
        'task_type': row.get('task_type'),
        'pedido_id': None,
        'bling_id': metadata.get('bling_id'),
        'numero_loja': metadata.get('numero_loja'),
        'payload_summary': metadata,
        'raw': row,
    }


def _dedupe_by_identity(items):
    seen = set()
    result = []
    for item in items:
        key = (
            item.get('source'),
            item.get('id'),
            item.get('timestamp'),
            item.get('stage'),
            item.get('status'),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


@tasks_api_bp.route('/execution-logs', methods=['GET'])
@check_permission('central_operacoes', 'ler')
def list_task_execution_logs():
    """
    List task execution logs with optional filtering.
    
    Query parameters:
    - status: Filter by status (PENDING, PROCESSING, COMPLETED, FAILED)
    - task_type: Filter by task type
    - task_name: Filter by task name
    - limit: Maximum number of records to return (default: 100)
    - offset: Offset for pagination (default: 0)
    """
    try:
        status = request.args.get('status')
        task_type = request.args.get('task_type')
        task_name = request.args.get('task_name')
        limit = max(1, min(200, int(request.args.get('limit', 50))))
        offset = max(0, int(request.args.get('offset', 0)))
        
        query = supabase_db.table('task_execution_logs').select('*', count='exact')
        
        if status:
            query = query.eq('status', status)
        if task_type:
            query = query.eq('task_type', task_type)
        if task_name:
            query = query.ilike('task_name', f'%{task_name}%')
        
        # Order by created_at descending
        query = query.order('created_at', desc=True)
        
        # Apply pagination
        query = query.range(offset, offset + limit - 1)
        
        response = query.execute()
        
        return jsonify({
            'success': True,
            'data': _sanitize(response.data or []),
            'count': int(getattr(response, 'count', 0) or 0),
            'limit': limit,
            'offset': offset,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_worker_logs_bp.route('/api/v2/admin/worker-logs', methods=['GET'])
@check_permission('central_operacoes', 'ler')
def list_admin_worker_logs():
    """
    Busca logs de ingest e de task execution para troubleshooting.

    Query parameters:
    - since: início do intervalo ISO
    - until: fim do intervalo ISO
    - q: texto livre
    - status: filtro por status
    - stage: filtro por stage/task_name
    - bling_id: filtro por id do pedido Bling
    - numero_loja: filtro por numeroLoja/codigo_pedido
    - correlation_id: filtro por correlation_id
    - page: página atual (default 1)
    - per_page: itens por página (default 50)
    """
    try:
        since = request.args.get('since')
        until = request.args.get('until')
        q = (request.args.get('q') or '').strip()
        status = request.args.get('status')
        stage = request.args.get('stage')
        bling_id = request.args.get('bling_id')
        numero_loja = request.args.get('numero_loja')
        correlation_id = request.args.get('correlation_id')
        page = max(1, int(request.args.get('page', 1)))
        per_page = max(1, min(int(request.args.get('per_page', 50)), 200))
        offset = (page - 1) * per_page

        ingest_query = supabase_db.table('pedido_ingest_log').select('*', count='exact')
        task_query = supabase_db.table('task_execution_logs').select('*', count='exact')

        if since:
            ingest_query = ingest_query.gte('created_at', since)
            task_query = task_query.gte('created_at', since)
        if until:
            ingest_query = ingest_query.lte('created_at', until)
            task_query = task_query.lte('created_at', until)
        if status:
            status_norm = status.strip()
            ingest_query = ingest_query.eq('status', status_norm.lower())
            task_query = task_query.eq('status', status_norm.upper())
        if stage:
            ingest_query = ingest_query.ilike('stage', f'%{stage}%')
            task_query = task_query.ilike('task_name', f'%{stage}%')
        if bling_id:
            ingest_query = ingest_query.eq('bling_id', bling_id)
        if numero_loja:
            ingest_query = ingest_query.eq('numero_loja', str(numero_loja))
        if correlation_id:
            ingest_query = ingest_query.eq('correlation_id', correlation_id)
            task_query = task_query.eq('correlation_id', correlation_id)
        if q:
            ingest_query = ingest_query.or_(f"message.ilike.%{q}%,stage.ilike.%{q}%")
            task_query = task_query.or_(f"error_message.ilike.%{q}%,task_name.ilike.%{q}%")

        # Fetch only enough rows from each ordered source to assemble this page.
        # The merged history remains bounded even when the underlying logs grow.
        fetch_end = offset + per_page - 1
        ingest_response = ingest_query.order('created_at', desc=True).range(0, fetch_end).execute()
        task_response = task_query.order('created_at', desc=True).range(0, fetch_end).execute()
        ingest_rows = ingest_response.data or []
        task_rows = task_response.data or []

        merged = [_normalize_ingest_log(row) for row in ingest_rows] + [_normalize_task_log(row) for row in task_rows]
        merged = _dedupe_by_identity(merged)
        merged.sort(key=_sort_key, reverse=True)

        total = int(getattr(ingest_response, 'count', 0) or 0) + int(getattr(task_response, 'count', 0) or 0)
        items = merged[offset:offset + per_page]

        return jsonify({
            'success': True,
            'data': _sanitize(items),
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page if total else 0,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/execution-logs/<task_log_id>', methods=['GET'])
@check_permission('central_operacoes', 'ler')
def get_task_execution_log_details(task_log_id):
    """
    Get detailed information about a specific task execution log.
    """
    try:
        response = supabase_db.table('task_execution_logs').select('*').eq('id', task_log_id).execute()
        
        if not response.data:
            return jsonify({'success': False, 'error': 'Task log not found'}), 404
        
        return jsonify({
            'success': True,
            'data': _sanitize(response.data[0])
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/execution-logs/<task_log_id>/retry', methods=['POST'])
@admin_required
def retry_task(task_log_id):
    return jsonify({'success': False,
                    'error': 'Esta execução não pode ser reenviada pelo histórico. Use a ação de reprocessamento do fluxo correspondente.'}), 410


@tasks_api_bp.route('/execution-logs/<task_log_id>/cancel', methods=['POST'])
@admin_required
def cancel_task(task_log_id):
    return jsonify({'success': False,
                    'error': 'O histórico não controla o cancelamento da tarefa original.'}), 410


@tasks_api_bp.route('/stats', methods=['GET'])
@check_permission('central_operacoes', 'ler')
def get_task_stats():
    """
    Get statistics about task execution logs.
    """
    try:
        table = supabase_db.table('task_execution_logs')
        total_response = table.select('id', count='exact', head=True).execute()
        total = int(getattr(total_response, 'count', 0) or 0)
        status_counts = {}
        for status in ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED'):
            result = (table.select('id', count='exact', head=True)
                      .eq('status', status).execute())
            status_counts[status] = int(getattr(result, 'count', 0) or 0)
        stats = {
            'total': total,
            'pending': status_counts['PENDING'],
            'processing': status_counts['PROCESSING'],
            'completed': status_counts['COMPLETED'],
            'failed': status_counts['FAILED'],
            'cancelled': status_counts['CANCELLED']
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# REPROCESSING ENDPOINTS
# ============================================================================

@tasks_api_bp.route('/stock/reprocess-events', methods=['POST'])
@admin_required
def reprocess_events():
    """
    Reprocess unprocessed eventos_producao_v2.
    
    Triggers the stock consolidation worker to process unprocessed events.
    """
    try:
        from nistiprint_shared.services.consolidador_estoque import consolidador_estoque
        import asyncio
        
        # Process a batch of unprocessed events
        loop = asyncio.get_event_loop()
        stats = loop.run_until_complete(consolidador_estoque.processar_lote(limit=50))
        
        return jsonify({
            'success': True,
            'message': 'Eventos reprocessados com sucesso',
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/stock/reconcile-item/<item_id>', methods=['POST'])
@admin_required
def reconcile_item(item_id):
    """
    Trigger reconciliation for a specific item.
    
    Forces reconciliation of stock for a specific demand item.
    """
    try:
        from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
        
        # Trigger reconciliation for the specific item
        result = motor_reconciliacao_estoque.reconciliar_item(item_id)
        
        return jsonify({
            'success': True,
            'message': f'Item {item_id} reconciliado com sucesso',
            'result': result
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
