"""Permission-scoped activity and immutable audit read APIs."""
from datetime import datetime, timedelta, timezone
import re

from flask import Blueprint, jsonify, request

from nistiprint_shared.database.supabase_db_service import supabase_db
from routes.auth import check_permission

activity_api_bp = Blueprint('activity_api', __name__)
_SENSITIVE_KEY = re.compile(
    r'(?i)(password|senha|token|secret|api.?key|authorization|credential|access_key|'
    r'service.?role.?key|partner.?key|private.?key)'
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)((?:access|refresh|id)?[_-]?(?:token|secret|password|senha)(?:[_-]?hash)?|"
    r"(?:service[_-]?role|service|partner|private|access|api)[_-]?key|authorization|credential)"
    r"(\s*[\"'=:\s]+)([^,\s\"'&}]+)"
)


def _sanitize(value):
    if isinstance(value, dict):
        return {key: ('[redigido]' if _SENSITIVE_KEY.search(str(key)) else _sanitize(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub(r'\1\2[redigido]', value)
    return value


def _page_args():
    page = max(1, request.args.get('page', 1, type=int))
    limit = max(1, min(200, request.args.get('limit', 50, type=int)))
    return page, limit, (page - 1) * limit


@activity_api_bp.get('/api/v2/operations/global')
@check_permission('central_operacoes', 'ler')
def list_global_operations():
    page, limit, offset = _page_args()
    query = supabase_db.table('operacoes_assincronas').select('*', count='exact')
    for param, column in (('status', 'status'), ('categoria', 'categoria'), ('owner_user_id', 'owner_user_id')):
        value = request.args.get(param)
        if value:
            if column == 'owner_user_id':
                try:
                    value = int(value)
                except ValueError:
                    return jsonify({'success': False, 'error': 'Identificador de usuário inválido.'}), 400
            query = query.eq(column, value)
    if request.args.get('from'):
        query = query.gte('created_at', request.args['from'])
    if request.args.get('to'):
        query = query.lte('created_at', request.args['to'])
    try:
        result = query.order('updated_at', desc=True).range(offset, offset + limit - 1).execute()
        return jsonify({
            'success': True,
            'data': _sanitize(result.data or []),
            'pagination': {'page': page, 'limit': limit, 'total': int(getattr(result, 'count', 0) or 0)},
        })
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível consultar as operações.'}), 503


@activity_api_bp.get('/api/v2/auditoria')
@check_permission('auditoria', 'ler')
def list_audit_events():
    page, limit, offset = _page_args()
    query = supabase_db.table('eventos_auditoria').select('*', count='exact')
    event_type = request.args.get('event_type')
    user_id = request.args.get('user_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    entity_type = request.args.get('entity_type')
    entity_id = request.args.get('entity_id')
    if event_type:
        query = query.eq('tipo_evento', event_type[:100])
    if user_id:
        try:
            query = query.eq('usuario_id', int(user_id))
        except ValueError:
            return jsonify({'success': False, 'error': 'Identificador de usuário inválido.'}), 400
    if start_date:
        try:
            stamp = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Data inicial inválida.'}), 400
        query = query.gte('created_at', stamp.isoformat())
    if end_date:
        try:
            stamp = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'success': False, 'error': 'Data final inválida.'}), 400
        if len(end_date) == 10:
            stamp += timedelta(days=1)
        query = query.lt('created_at', stamp.isoformat())
    if entity_type:
        query = query.eq('entidade_afetada', entity_type[:100])
    if entity_id:
        try:
            query = query.eq('registro_id', int(entity_id))
        except ValueError:
            return jsonify({'success': False, 'error': 'Identificador de entidade inválido.'}), 400
    try:
        result = query.order('created_at', desc=True).range(offset, offset + limit - 1).execute()
        return jsonify({
            'success': True,
            'events': _sanitize(result.data or []),
            'pagination': {'page': page, 'limit': limit, 'total': int(getattr(result, 'count', 0) or 0)},
        })
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível carregar os eventos de auditoria.'}), 503


@activity_api_bp.get('/api/v2/auditoria/<int:event_id>')
@check_permission('auditoria', 'ler')
def get_audit_event(event_id):
    try:
        result = (supabase_db.table('eventos_auditoria').select('*')
                  .eq('id', event_id).limit(1).execute())
        if not result.data:
            return jsonify({'success': False, 'error': 'Evento não encontrado.'}), 404
        return jsonify({'success': True, 'event': _sanitize(result.data[0])})
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível consultar o evento.'}), 503


@activity_api_bp.get('/api/v2/auditoria/entidade/<entity_type>/<int:entity_id>')
@check_permission('auditoria', 'ler')
def list_audit_entity_events(entity_type, entity_id):
    page, limit, offset = _page_args()
    try:
        result = (supabase_db.table('eventos_auditoria').select('*', count='exact')
                  .eq('entidade_afetada', entity_type[:100]).eq('registro_id', entity_id)
                  .order('created_at', desc=True).range(offset, offset + limit - 1).execute())
        return jsonify({
            'success': True,
            'events': _sanitize(result.data or []),
            'pagination': {'page': page, 'limit': limit, 'total': int(getattr(result, 'count', 0) or 0)},
        })
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível consultar a entidade.'}), 503
