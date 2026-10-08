import json
import time
from datetime import datetime
from flask import Blueprint, request, Response, jsonify
from nistiprint_shared.services.notification_service import notification_service
from nistiprint_shared.services.async_operation_service import async_operation_service
from routes.auth import login_required, admin_required, get_current_user, check_permission
from nistiprint_shared.services.permissao_service import permissao_service
from nistiprint_shared.services.usuario_service import usuario_service
from nistiprint_shared.models.setor import Setor


notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/v2/notifications')


@notifications_bp.route('/stream', methods=['GET'])
@login_required
def notification_stream():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Autenticação requerida'}), 401

    def event_stream(user=user):
        user_id = str(user['id'])
        sector = user.get('setor_nome')
        sector_id = user.get('setor_id')
        initial_permissions = permissao_service.get_setor_permissions(sector_id)
        initial_demand_permissions = permissao_service.get_demand_permissions(sector_id)
        subscription = None
        last_session_check = time.monotonic()
        try:
            subscription = notification_service.subscribe_user(user_id, sector)
            notification_service.register_client(user_id, sector or 'unknown', None)
            yield f"data: {json.dumps({'type': 'welcome', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            last_heartbeat = time.monotonic()
            while True:
                message = subscription.get_message(timeout=10)
                if time.monotonic() - last_session_check >= 30:
                    current = usuario_service.get_by_id(int(user_id))
                    current_sector = Setor.query.filter_by(id=current.get('setor_id'), ativo=True).first() if current else None
                    current_permissions = permissao_service.get_setor_permissions(current.get('setor_id')) if current else {}
                    current_demand_permissions = permissao_service.get_demand_permissions(current.get('setor_id')) if current else {}
                    if (
                        not current or not current.get('ativo') or not current_sector
                        or int(current.get('session_version') or 0) != int(user.get('session_version') or 0)
                        or int(current.get('setor_id') or 0) != int(sector_id or 0)
                    ):
                        yield f"data: {json.dumps({'type': 'auth.revoked'})}\n\n"
                        break
                    if current_permissions != initial_permissions or current_demand_permissions != initial_demand_permissions:
                        yield f"data: {json.dumps({'type': 'permissions.changed'})}\n\n"
                        break
                    last_session_check = time.monotonic()
                if message and message.get('data'):
                    payload = json.loads(message['data'])
                    if str(payload.get('exclude_user_id') or '') == user_id:
                        continue
                    if payload.get('target_sector') and payload.get('target_sector') != sector:
                        continue
                    yield f"data: {json.dumps(payload)}\n\n"
                elif time.monotonic() - last_heartbeat >= 25:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
                    last_heartbeat = time.monotonic()
        except GeneratorExit:
            pass
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Conexão temporariamente indisponível.'})}\n\n"
        finally:
            notification_service.unregister_client(user_id)
            if subscription:
                subscription.close()

    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@notifications_bp.route('/center', methods=['GET'])
@login_required
def get_activity_center():
    user = get_current_user()
    try:
        limit = max(1, min(200, request.args.get('limit', 50, type=int)))
        offset = max(0, request.args.get('offset', 0, type=int))
        data = async_operation_service.list_center(int(user['id']), limit=limit, offset=offset)
        return jsonify({'success': True, 'data': data})
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível carregar a central de atividade.'}), 500


@notifications_bp.route('/operations/<operation_id>', methods=['GET'])
@login_required
def get_user_operation(operation_id):
    user = get_current_user()
    try:
        operation = async_operation_service.get_user_operation(int(user['id']), operation_id)
        if not operation:
            return jsonify({'success': False, 'error': 'Processo não encontrado.'}), 404
        return jsonify({'success': True, 'data': operation})
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível consultar o processo.'}), 500


@notifications_bp.route('/<int:notification_id>/read', methods=['PATCH'])
@login_required
def mark_notification_read(notification_id):
    user = get_current_user()
    try:
        notification = async_operation_service.mark_notification_read(int(user['id']), notification_id)
        if not notification:
            return jsonify({'success': False, 'error': 'Notificação não encontrada.'}), 404
        return jsonify({'success': True, 'data': notification})
    except Exception:
        return jsonify({'success': False, 'error': 'Não foi possível atualizar a notificação.'}), 500


@notifications_bp.route('/send', methods=['POST'])
@admin_required
def send_notification():
    user = get_current_user()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    event_type = data.get('event_type', 'generic')
    message = data.get('message', '')
    target_sector = data.get('target_sector')
    target_user_id = data.get('target_user_id')
    payload = data.get('payload') or {}
    notification_data = {
        'type': 'notification.created',
        'event_type': event_type,
        'message': message,
        'sender_user_id': user['id'],
        'sender_name': user['nome'],
        'timestamp': datetime.utcnow().isoformat(),
        'payload': payload,
    }

    if target_user_id:
        notification_id = notification_service.create_notification(
            event_type=event_type,
            user_id=str(target_user_id),
            payload={
                **payload,
                'title': payload.get('title') or event_type,
                'message': message,
                'sender_name': user['nome'],
            },
            target_sector=target_sector,
        )
    else:
        notification_service.broadcast_notification(
            notification_data,
            target_sector=target_sector,
            exclude_user_id=str(user['id']),
        )
        notification_id = None

    return jsonify({
        'success': True,
        'notification_id': notification_id,
        'message': 'Notification sent successfully',
    })


@notifications_bp.route('/connected-users', methods=['GET'])
@admin_required
def get_connected_users():
    return jsonify({'connected_users_count': notification_service.get_connected_users_count()})


@notifications_bp.route('/trigger-demand-update', methods=['POST'])
@check_permission('demanda_producao', 'editar')
def trigger_demand_update_notification():
    user = get_current_user()
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    demanda_id = data.get('demanda_id')
    item_id = data.get('item_id')
    action = data.get('action', 'updated')
    if not demanda_id:
        return jsonify({'error': 'demanda_id is required'}), 400

    notification_data = {
        'type': 'notification.created',
        'event_type': 'demand_update',
        'message': f'Demanda {demanda_id} foi atualizada',
        'demanda_id': demanda_id,
        'item_id': item_id,
        'action': action,
        'updated_by': user['nome'],
        'timestamp': datetime.utcnow().isoformat(),
        'sector': data.get('sector'),
    }
    notification_service.broadcast_notification(
        notification_data,
        target_sector=data.get('sector'),
        exclude_user_id=str(user['id']),
    )
    notification_id = notification_service.create_notification(
        event_type='DEMAND_UPDATE',
        user_id=str(user['id']),
        payload={
            'title': f'Demanda {demanda_id} atualizada',
            'message': notification_data['message'],
            'demanda_id': demanda_id,
            'item_id': item_id,
            'action': action,
        },
        target_sector=data.get('sector'),
    )
    return jsonify({'success': True, 'notification_id': notification_id})
