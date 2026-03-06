import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from flask import jsonify
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
        self.notifications_table = supabase_db.table('notificacoes')
        
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
                        sse_message = f"data: {json.dumps(notification_data)}\n\n"
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
        with self.lock:
            if user_id in self.clients:
                try:
                    client_info = self.clients[user_id]
                    connection = client_info['connection']
                    if connection:
                        sse_message = f"data: {json.dumps(notification_data)}\n\n"
                        connection.put(sse_message)
                except Exception as e:
                    print(f"Error sending notification to user {user_id}: {str(e)}")
                    del self.clients[user_id]
    
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
        notification_data = {
            'event_type': event_type,
            'user_id': user_id,
            'payload': payload,
            'target_sector': target_sector,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat()
        }

        # Store in Supabase
        response = self.notifications_table.insert(notification_data).execute()
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

        return notification_id


# Global instance for use throughout the application
notification_service = NotificationService()

