import json
import queue
from datetime import datetime
from flask import Blueprint, request, Response, session, jsonify
from flask_cors import CORS
from services.notification_service import notification_service
from routes.auth import login_required, get_current_user


notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/v2/notifications')


@notifications_bp.route('/stream', methods=['GET'])
@login_required
def notification_stream():
    """
    SSE endpoint for real-time notifications.
    Clients connect to this endpoint to receive live notifications.
    """
    # Get current user info outside the generator to avoid request context issues
    user = get_current_user()
    if not user:
        return Response(f"data: {json.dumps({'error': 'Authentication required'})}\n\n", mimetype='text/event-stream')

    def event_stream(user=user):
        # User is passed as parameter to avoid session access inside generator
        
        user_id = str(user['id'])
        sector = user.get('setor_nome', 'unknown')
        
        # Create a queue for this connection
        q = queue.Queue()
        
        try:
            # Register this client connection
            notification_service.register_client(user_id, sector, q)
            
            # Send welcome message
            welcome_msg = {
                'type': 'welcome',
                'message': 'Connected to notification service',
                'user_id': user_id,
                'sector': sector,
                'timestamp': str(datetime.utcnow())
            }
            yield f"data: {json.dumps(welcome_msg)}\n\n"
            
            # Listen for messages from the queue
            while True:
                try:
                    # Get message from queue with timeout
                    message = q.get(timeout=30)  # 30 second timeout
                    
                    # Send the message to the client
                    yield message
                    
                except queue.Empty:
                    # Send heartbeat to keep connection alive
                    heartbeat = {
                        'type': 'heartbeat',
                        'timestamp': str(datetime.utcnow())
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                    
        except GeneratorExit:
            # Client disconnected
            pass
        except Exception as e:
            error_msg = {
                'type': 'error',
                'message': f'Connection error: {str(e)}',
                'timestamp': str(datetime.utcnow())
            }
            yield f"data: {json.dumps(error_msg)}\n\n"
        finally:
            # Unregister client when connection closes
            notification_service.unregister_client(user_id)
    
    # Return the event stream response
    from datetime import datetime
    response = Response(event_stream(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    # CORS headers for SSE with credentials
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', 'http://localhost:5173')
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = 'Cache-Control'
    return response


@notifications_bp.route('/send', methods=['POST'])
@login_required
def send_notification():
    """
    API endpoint to send a notification to specific users or sectors.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    
    event_type = data.get('event_type', 'generic')
    message = data.get('message', '')
    target_sector = data.get('target_sector')
    target_user_id = data.get('target_user_id')
    payload = data.get('payload', {})
    
    notification_data = {
        'event_type': event_type,
        'message': message,
        'sender_user_id': user['id'],
        'sender_name': user['nome'],
        'timestamp': str(datetime.utcnow()),
        'payload': payload
    }
    
    if target_user_id:
        # Send to specific user
        notification_service.send_notification_to_user(target_user_id, notification_data)
    else:
        # Broadcast to sector or all users
        notification_service.broadcast_notification(
            notification_data, 
            target_sector=target_sector,
            exclude_user_id=str(user['id'])
        )
    
    # Create notification record
    notification_id = notification_service.create_notification(
        event_type=event_type,
        user_id=str(user['id']),
        payload=payload,
        target_sector=target_sector
    )
    
    return jsonify({
        'success': True,
        'notification_id': notification_id,
        'message': 'Notification sent successfully'
    })


@notifications_bp.route('/connected-users', methods=['GET'])
@login_required
def get_connected_users():
    """
    Get information about connected users.
    """
    connected_count = notification_service.get_connected_users_count()
    user = get_current_user()
    
    # Only admins can see all connected users
    if user and user.get('is_admin', False):
        connected_users_by_sector = {}
        # This would require expanding the notification service to expose this info
        # For now, just return the count
        pass
    
    return jsonify({
        'connected_users_count': connected_count
    })


@notifications_bp.route('/trigger-demand-update', methods=['POST'])
@login_required
def trigger_demand_update_notification():
    """
    Trigger a notification for demand updates.
    This endpoint can be called internally when demand items are updated.
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    
    demanda_id = data.get('demanda_id')
    item_id = data.get('item_id')
    action = data.get('action', 'updated')
    sector = data.get('sector')
    
    if not demanda_id:
        return jsonify({'error': 'demanda_id is required'}), 400
    
    # Create notification message
    notification_data = {
        'event_type': 'demand_update',
        'message': f'Demanda {demanda_id} was updated',
        'demanda_id': demanda_id,
        'item_id': item_id,
        'action': action,
        'updated_by': user['nome'],
        'timestamp': str(datetime.utcnow()),
        'sector': sector
    }
    
    # Broadcast to relevant sector or all users
    notification_service.broadcast_notification(
        notification_data,
        target_sector=sector,
        exclude_user_id=str(user['id'])
    )
    
    # Create notification record
    notification_id = notification_service.create_notification(
        event_type='DEMAND_UPDATE',
        user_id=str(user['id']),
        payload={
            'demanda_id': demanda_id,
            'item_id': item_id,
            'action': action
        },
        target_sector=sector
    )
    
    return jsonify({
        'success': True,
        'notification_id': notification_id,
        'message': 'Demand update notification sent'
    })
