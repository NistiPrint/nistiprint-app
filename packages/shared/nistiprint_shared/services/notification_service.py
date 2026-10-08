import json
import os
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import jsonify
import redis
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.auditoria_service import auditoria_service


class NotificationService:
    """
    Service for managing real-time notifications across users.
    Uses Server-Sent Events (SSE) to broadcast notifications to connected clients.
    """

    def __init__(self):
        self.clients = {}  # Dictionary to track connected clients
        self.lock = threading.Lock()  # Thread lock for thread-safe operations
        self.redis = redis.Redis.from_url(
            os.environ.get('CELERY_BROKER_URL', 'redis://redis-celery:6379/0'),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )

    @property
    def notifications_table(self):
        return supabase_db.table('notificacoes')

    @staticmethod
    def _user_channel(user_id: str) -> str:
        return f"np:notifications:user:{user_id}"

    def publish_user_event(self, user_id: str, event: Dict[str, Any]):
        """Fan out an event to the authenticated user's SSE connections."""
        try:
            self.redis.publish(self._user_channel(str(user_id)), json.dumps(event, default=str))
        except Exception as exc:
            # The database remains the source of truth; the client refreshes its
            # snapshot after reconnecting if Redis is temporarily unavailable.
            print(f"Could not publish notification event for user {user_id}: {exc}")

    def subscribe_user(self, user_id: str, sector: str | None = None):
        """Subscribe to personal events plus legacy sector and global notices."""
        subscription = self.redis.pubsub(ignore_subscribe_messages=True)
        channels = [self._user_channel(str(user_id)), "np:notifications:all"]
        if sector:
            channels.append(f"np:notifications:sector:{sector}")
        subscription.subscribe(*channels)
        return subscription
        
    def register_client(self, user_id: str, sector: str, sse_connection):
        """
        Register a client connection for receiving notifications.
        
        Args:
            user_id: The ID of the user
            sector: The sector of the user
            sse_connection: The SSE connection object
        """
        with self.lock:
            if user_id not in self.clients:
                self.clients[user_id] = {
                    'sector': sector,
                    'connection': sse_connection,
                    'last_seen': datetime.utcnow(),
                    'connected_at': datetime.utcnow()
                }
            else:
                # Update connection if user reconnects
                self.clients[user_id].update({
                    'sector': sector,
                    'connection': sse_connection,
                    'last_seen': datetime.utcnow()
                })
    
    def unregister_client(self, user_id: str):
        """
        Unregister a client connection.
        
        Args:
            user_id: The ID of the user to unregister
        """
        with self.lock:
            if user_id in self.clients:
                del self.clients[user_id]
    
    def broadcast_notification(self, notification_data: Dict[str, Any], target_sector: Optional[str] = None, 
                             exclude_user_id: Optional[str] = None):
        """
        Broadcast a notification to all connected clients or specific sector.
        
        Args:
            notification_data: The notification data to broadcast
            target_sector: Optional sector to target (None for all sectors)
            exclude_user_id: Optional user ID to exclude from broadcast (typically the user who triggered the action)
        """
        event = {
            **notification_data,
            "target_sector": target_sector,
            "exclude_user_id": str(exclude_user_id) if exclude_user_id else None,
        }
        channel = f"np:notifications:sector:{target_sector}" if target_sector else "np:notifications:all"
        try:
            self.redis.publish(channel, json.dumps(event, default=str))
        except Exception as exc:
            print(f"Could not publish broadcast notification: {exc}")

        with self.lock:
            for user_id, client_info in list(self.clients.items()):
                # Skip if this is the user who triggered the action
                if exclude_user_id and user_id == exclude_user_id:
                    continue
                
                # Skip if targeting specific sector and client is not in that sector
                if target_sector and client_info['sector'] != target_sector:
                    continue
                
                try:
                    # Send notification via SSE
                    connection = client_info['connection']
                    if connection:
                        # Format as SSE message
                        sse_message = f"data: {json.dumps(event)}\n\n"
                        connection.put(sse_message)
                except Exception as e:
                    # Remove client if connection fails
                    print(f"Error sending notification to user {user_id}: {str(e)}")
                    if user_id in self.clients:
                        del self.clients[user_id]
    
    def send_notification_to_user(self, user_id: str, notification_data: Dict[str, Any]):
        """
        Send a notification to a specific user.
        
        Args:
            user_id: The ID of the target user
            notification_data: The notification data to send
        """
        self.publish_user_event(user_id, notification_data)
    
    def get_connected_users_count(self) -> int:
        """
        Get the count of currently connected users.
        
        Returns:
            Number of connected users
        """
        with self.lock:
            return len(self.clients)
    
    def get_connected_users_by_sector(self, sector: str) -> List[str]:
        """
        Get list of connected users in a specific sector.
        
        Args:
            sector: The sector to filter by
            
        Returns:
            List of user IDs in the specified sector
        """
        with self.lock:
            return [user_id for user_id, client_info in self.clients.items() 
                   if client_info['sector'] == sector]
    
    def create_notification(self, event_type: str, user_id: str, payload: Dict[str, Any],
                          target_sector: Optional[str] = None) -> str:
        """
        Create and store a notification in the database.

        Args:
            event_type: Type of the event that triggered the notification
            user_id: ID of the user who triggered the event
            payload: Additional data for the notification
            target_sector: Optional sector to target with this notification

        Returns:
            ID of the created notification
        """
        payload = payload or {}
        now = datetime.utcnow().isoformat()
        title = str(payload.get('title') or payload.get('titulo') or 'Notificação')
        message = str(payload.get('message') or payload.get('mensagem') or '')
        operation_id = payload.get('operation_id') or payload.get('operacao_id')
        notification_data = {
            'owner_user_id': int(user_id),
            'operacao_id': operation_id,
            'event_type': event_type,
            'terminal_notification': bool(
                operation_id and event_type in {'operation.completed', 'operation.failed'}
            ),
            'titulo': title[:255],
            'mensagem': message,
            'tipo': payload.get('tipo') or 'informativo',
            'nivel_critica': payload.get('nivel_critica') or 'MEDIA',
            'destinatarios': {'user_id': int(user_id), 'target_sector': target_sector},
            'lida': False,
            'data_envio': now,
            'dados_adicionais': payload,
            'created_at': now,
            'updated_at': now,
        }

        if operation_id and event_type in {'operation.completed', 'operation.failed'}:
            existing = (self.notifications_table.select('id').eq('operacao_id', operation_id)
                        .eq('owner_user_id', int(user_id)).eq('event_type', event_type)
                        .limit(1).execute().data or [])
            if existing:
                return str(existing[0]['id'])

        try:
            response = self.notifications_table.insert(notification_data).execute()
        except Exception:
            if operation_id and event_type in {'operation.completed', 'operation.failed'}:
                existing = (self.notifications_table.select('id').eq('operacao_id', operation_id)
                            .eq('owner_user_id', int(user_id)).eq('event_type', event_type)
                            .limit(1).execute().data or [])
                if existing:
                    return str(existing[0]['id'])
            raise
        if response.data:
            notification_id = str(response.data[0]['id'])
        else:
            # Generate a fallback ID if insertion fails
            notification_id = str(datetime.utcnow().timestamp())

        # Log the notification event
        auditoria_service.log_event(
            event_type='NOTIFICATION_CREATED',
            payload={
                'notification_id': notification_id,
                'event_type': event_type,
                'user_id': user_id,
                'target_sector': target_sector
            },
            user_id=user_id
        )

        self.publish_user_event(user_id, {
            'type': 'notification.created',
            'notification': {
                **notification_data,
                'id': notification_id,
                'read_at': None,
            },
        })

        return notification_id


# Global instance for use throughout the application
notification_service = NotificationService()

