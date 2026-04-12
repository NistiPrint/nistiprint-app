"""
Task Management API Endpoints
Provides endpoints for monitoring and managing async task execution logs
"""
from flask import Blueprint, request, jsonify
from routes.auth import login_required, admin_required
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.utils.date_utils import get_now_iso

tasks_api_bp = Blueprint('tasks_api', __name__, url_prefix='/api/v2/tasks')


@tasks_api_bp.route('/execution-logs', methods=['GET'])
@login_required
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
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        query = supabase_db.table('task_execution_logs').select('*')
        
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
            'data': response.data or [],
            'count': len(response.data) if response.data else 0
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/execution-logs/<task_log_id>', methods=['GET'])
@login_required
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
            'data': response.data[0]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/execution-logs/<task_log_id>/retry', methods=['POST'])
@admin_required
def retry_task(task_log_id):
    """
    Manually retry a failed task.
    
    This endpoint updates the task status to PENDING and increments retry count.
    The actual task execution will be picked up by the worker.
    """
    try:
        # Get current task log
        response = supabase_db.table('task_execution_logs').select('*').eq('id', task_log_id).execute()
        
        if not response.data:
            return jsonify({'success': False, 'error': 'Task log not found'}), 404
        
        task_log = response.data[0]
        
        # Only allow retry for failed tasks
        if task_log.get('status') != 'FAILED':
            return jsonify({'success': False, 'error': 'Can only retry failed tasks'}), 400
        
        # Update task log for retry
        updates = {
            'status': 'PENDING',
            'retry_count': (task_log.get('retry_count') or 0) + 1,
            'last_retry_at': get_now_iso(),
            'error_message': None,
            'started_at': None,
            'finished_at': None
        }
        
        supabase_db.table('task_execution_logs').update(updates).eq('id', task_log_id).execute()
        
        return jsonify({
            'success': True,
            'message': 'Task queued for retry',
            'retry_count': updates['retry_count']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/execution-logs/<task_log_id>/cancel', methods=['POST'])
@admin_required
def cancel_task(task_log_id):
    """
    Cancel a pending or processing task.
    
    This endpoint updates the task status to CANCELLED.
    """
    try:
        # Get current task log
        response = supabase_db.table('task_execution_logs').select('*').eq('id', task_log_id).execute()
        
        if not response.data:
            return jsonify({'success': False, 'error': 'Task log not found'}), 404
        
        task_log = response.data[0]
        
        # Only allow cancel for pending or processing tasks
        if task_log.get('status') not in ['PENDING', 'PROCESSING']:
            return jsonify({'success': False, 'error': 'Can only cancel pending or processing tasks'}), 400
        
        # Update task log to cancelled
        updates = {
            'status': 'CANCELLED',
            'finished_at': get_now_iso()
        }
        
        supabase_db.table('task_execution_logs').update(updates).eq('id', task_log_id).execute()
        
        return jsonify({
            'success': True,
            'message': 'Task cancelled successfully'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/stats', methods=['GET'])
@login_required
def get_task_stats():
    """
    Get statistics about task execution logs.
    """
    try:
        # Get counts by status
        response = supabase_db.table('task_execution_logs').select('status').execute()
        
        if not response.data:
            return jsonify({
                'success': True,
                'stats': {
                    'total': 0,
                    'pending': 0,
                    'processing': 0,
                    'completed': 0,
                    'failed': 0,
                    'cancelled': 0
                }
            })
        
        total = len(response.data)
        stats = {
            'total': total,
            'pending': sum(1 for t in response.data if t.get('status') == 'PENDING'),
            'processing': sum(1 for t in response.data if t.get('status') == 'PROCESSING'),
            'completed': sum(1 for t in response.data if t.get('status') == 'COMPLETED'),
            'failed': sum(1 for t in response.data if t.get('status') == 'FAILED'),
            'cancelled': sum(1 for t in response.data if t.get('status') == 'CANCELLED')
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


@tasks_api_bp.route('/stock/reprocess-fila', methods=['POST'])
@admin_required
def reprocess_fila():
    """
    Reprocess fila_processamento_estoque.
    
    Triggers the stock reconciliation motor to process the legacy queue.
    """
    try:
        from nistiprint_shared.services.motor_reconciliacao_estoque import motor_reconciliacao_estoque
        
        # Process a batch of items from the queue
        stats = motor_reconciliacao_estoque.processar_fila_unificada(limit=50)
        
        return jsonify({
            'success': True,
            'message': 'Fila reprocessada com sucesso',
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@tasks_api_bp.route('/stock/reconcile-item/<item_id>', methods=['POST'])
@login_required
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
