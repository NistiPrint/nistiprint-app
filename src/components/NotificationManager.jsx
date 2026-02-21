import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { checkActionRequired, getNotificationMessage } from '@/lib/notificationLogic';
import { toast } from 'sonner';
import { Bell } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { useNavigate } from 'react-router-dom';

export function NotificationManager() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [hasUnread, setHasUnread] = useState(false);
  const eventSourceRef = useRef(null);
  const processedDemandasRef = useRef(new Set());
  const mountedRef = useRef(true);

  // Solicitar permissão do navegador ao montar
  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  // Setup SSE connection when user is authenticated
  useEffect(() => {
    if (!user) return;

    // Close any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    // Create new SSE connection
    const eventSource = new EventSource('/api/v2/notifications/stream');
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle different types of notifications
        if (data.type === 'welcome') {
          console.log('Connected to notification service');
        } else if (data.type === 'heartbeat') {
          // Heartbeat received, connection is alive
        } else if (data.event_type === 'demand_progress_updated') {
          // Handle demand progress updates
          handleDemandProgressUpdate(data);
        } else if (data.event_type === 'demand_item_completed') {
          // Handle demand item completion
          handleDemandItemCompletion(data);
        } else if (data.event_type) {
          // Handle other types of notifications
          handleGenericNotification(data);
        }
      } catch (error) {
        console.error('Error parsing SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE connection error:', error);
      if (eventSource.readyState === EventSource.CLOSED && mountedRef.current) {
        // Attempt to reconnect after a delay
        setTimeout(() => {
          if (mountedRef.current) {
            // Restart the effect by causing a re-render or calling setup again
            window.location.reload(); // Simple approach, in production you'd want to restart the connection
          }
        }, 5000); // Retry after 5 seconds
      }
    };

    // Cleanup function
    return () => {
      mountedRef.current = false;
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [user]);

  const handleDemandProgressUpdate = (data) => {
    const { demanda_id, item_id, updated_by, changes } = data;

    // Create notification message
    const message = `Atualização na demanda ${demanda_id}: ${Object.keys(changes).join(', ')}`;

    // Show browser notification
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Atualização de Demanda - NistiPrint', {
        body: message,
        icon: '/vite.svg',
        tag: `demand-${demanda_id}`
      });
    }

    // Show toast notification
    toast.info(message, {
      action: {
        label: 'Ver',
        onClick: () => navigate(`/producao/demanda/${demanda_id}/dashboard`)
      }
    });

    // Add to notification list
    const newNotification = {
      id: `${demanda_id}-${Date.now()}`,
      title: `Demanda ${demanda_id}`,
      message: message,
      time: new Date(),
      read: false,
      type: 'demand_progress_update',
      demanda_id: demanda_id,
      item_id: item_id
    };

    setNotifications(prev => [newNotification, ...prev].slice(0, 20));
    setHasUnread(true);
  };

  const handleDemandItemCompletion = (data) => {
    const { demanda_id, item_id, quantidade_total } = data;

    // Create notification message
    const message = `Item finalizado na demanda ${demanda_id}`;

    // Show browser notification
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Item Finalizado - NistiPrint', {
        body: message,
        icon: '/vite.svg',
        tag: `completion-${demanda_id}`
      });
    }

    // Show toast notification
    toast.success(message, {
      action: {
        label: 'Ver',
        onClick: () => navigate(`/producao/demanda/${demanda_id}/dashboard`)
      }
    });

    // Add to notification list
    const newNotification = {
      id: `${demanda_id}-completion-${Date.now()}`,
      title: `Demanda ${demanda_id} - Concluída`,
      message: message,
      time: new Date(),
      read: false,
      type: 'demand_completion',
      demanda_id: demanda_id,
      item_id: item_id
    };

    setNotifications(prev => [newNotification, ...prev].slice(0, 20));
    setHasUnread(true);
  };

  const handleGenericNotification = (data) => {
    const { message, event_type, demanda_id } = data;

    // Show browser notification
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Notificação - NistiPrint', {
        body: message,
        icon: '/vite.svg',
        tag: `notification-${Date.now()}`
      });
    }

    // Show toast notification
    toast.info(message, {
      action: demanda_id ? {
        label: 'Ver',
        onClick: () => navigate(`/producao/demanda/${demanda_id}/dashboard`)
      } : undefined
    });

    // Add to notification list
    const newNotification = {
      id: `notification-${Date.now()}`,
      title: event_type || 'Notificação',
      message: message,
      time: new Date(),
      read: false,
      type: event_type || 'generic',
      demanda_id: demanda_id
    };

    setNotifications(prev => [newNotification, ...prev].slice(0, 20));
    setHasUnread(true);
  };

  const handleNotificationClick = (notif) => {
    if (notif.demanda_id) {
      navigate(`/producao/demanda/${notif.demanda_id}/dashboard`);
    }
    // Marcar como lida visualmente (opcional, pois recarregará ao navegar)
  };

  const clearNotifications = () => {
    setNotifications([]);
    setHasUnread(false);
  };

  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {hasUnread && (
            <span className="absolute top-2 right-2 h-2 w-2 rounded-full bg-red-600 animate-pulse" />
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex justify-between items-center">
          Notificações
          {notifications.length > 0 && (
            <Button variant="ghost" size="xs" onClick={clearNotifications} className="text-xs font-normal">
              Limpar
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {notifications.length === 0 ? (
          <div className="p-4 text-center text-sm text-gray-500">
            Nenhuma nova notificação.
          </div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {notifications.map((notif, index) => (
              <DropdownMenuItem key={`${notif.id}-${index}`} onClick={() => handleNotificationClick(notif)} className="cursor-pointer">
                <div className="flex flex-col gap-1">
                  <span className="font-medium text-sm">{notif.title}</span>
                  <span className="text-xs text-gray-500">{notif.message}</span>
                  <span className="text-[10px] text-gray-400">
                    {notif.time.toLocaleTimeString()}
                  </span>
                </div>
              </DropdownMenuItem>
            ))}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
