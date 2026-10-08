import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bell, BellOff, CheckCheck, CircleCheck, CircleX, Clock3, ExternalLink, Info, LoaderCircle, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuth } from '@/contexts/AuthContext';

const TERMINAL = new Set(['CONCLUIDO', 'ERRO']);
const BROWSER_PREF_KEY = 'nisti:browser-notifications-enabled';

const formatTime = (value) => {
  if (!value) return 'Agora';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Agora';
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
};

const statusPresentation = (status) => {
  switch (status) {
    case 'AGUARDANDO':
      return { label: 'Na fila', variant: 'info', Icon: Clock3 };
    case 'EM_ANDAMENTO':
      return { label: 'Em andamento', variant: 'info', Icon: LoaderCircle };
    case 'CONCLUIDO':
      return { label: 'Concluído', variant: 'success', Icon: CircleCheck };
    case 'ERRO':
      return { label: 'Falhou', variant: 'destructive', Icon: CircleX };
    default:
      return { label: 'Atualizado', variant: 'secondary', Icon: Info };
  }
};

function OperationRow({ operation, onOpen }) {
  const presentation = statusPresentation(operation.status);
  const Icon = presentation.Icon;
  const total = Number(operation.progresso_total);
  const current = Number(operation.progresso_atual);
  const hasCount = Number.isFinite(total) && total > 0 && Number.isFinite(current);

  return (
    <button
      type="button"
      onClick={() => onOpen(operation)}
      className="w-full rounded-lg border border-border/80 bg-card p-3 text-left transition-colors hover:border-primary/30 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className={'h-4 w-4 ' + (operation.status === 'EM_ANDAMENTO' ? 'animate-spin' : '')} aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-sm text-foreground">{operation.titulo}</span>
            <Badge variant={presentation.variant}>{presentation.label}</Badge>
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">{operation.mensagem || operation.etapa}</span>
          <span className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {operation.etapa && <span>{operation.etapa}</span>}
            {hasCount && <span className="font-medium tabular-nums text-foreground">{current} de {total}</span>}
            <span>{formatTime(operation.updated_at || operation.created_at)}</span>
          </span>
          {operation.erro_resumo && <span className="mt-2 block text-xs font-medium text-destructive">{operation.erro_resumo}</span>}
        </span>
        <ExternalLink className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </span>
    </button>
  );
}

export function NotificationManager() {
  const { user, refreshCurrentUser } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [operations, setOperations] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [browserEnabled, setBrowserEnabled] = useState(false);
  const [browserPermission, setBrowserPermission] = useState(
    typeof window !== 'undefined' && 'Notification' in window ? Notification.permission : 'unsupported',
  );
  const [tab, setTab] = useState('processos');
  const eventSourceRef = useRef(null);
  const mountedRef = useRef(false);
  const refreshingRef = useRef(false);
  const terminalToastIdsRef = useRef(new Set());
  const userIdRef = useRef(user?.id);
  userIdRef.current = user?.id;

  useEffect(() => {
    setOperations([]);
    setNotifications([]);
    setUnreadCount(0);
    refreshingRef.current = false;
    terminalToastIdsRef.current.clear();
  }, [user?.id]);

  const loadCenter = useCallback(async () => {
    if (!user || refreshingRef.current) return;
    const requestedUserId = user.id;
    refreshingRef.current = true;
    try {
      const response = await fetch('/api/v2/notifications/center', { credentials: 'same-origin' });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || 'Falha ao carregar atividade.');
      if (mountedRef.current && String(userIdRef.current) === String(requestedUserId)) {
        setOperations(result.data?.operations || []);
        setNotifications(result.data?.notifications || []);
        setUnreadCount(Number(result.data?.unread_count || 0));
        setLoadError(false);
      }
    } catch (error) {
      if (mountedRef.current && String(userIdRef.current) === String(requestedUserId)) setLoadError(true);
      console.warn('Falha ao sincronizar a central de atividade:', error);
    } finally {
      refreshingRef.current = false;
      if (mountedRef.current && String(userIdRef.current) === String(requestedUserId)) setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    mountedRef.current = true;
    setBrowserEnabled(localStorage.getItem(BROWSER_PREF_KEY) === 'true');
    loadCenter();
    const refreshTimer = window.setInterval(loadCenter, 30000);
    return () => {
      mountedRef.current = false;
      window.clearInterval(refreshTimer);
    };
  }, [loadCenter]);

  useEffect(() => {
    if (!user) return undefined;
    const source = new EventSource('/api/v2/notifications/stream');
    eventSourceRef.current = source;

    source.onopen = () => {
      loadCenter();
    };
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'auth.revoked') {
          source.close();
          window.location.assign('/login');
          return;
        }
        if (data.type === 'permissions.changed') {
          source.close();
          refreshCurrentUser().then(loadCenter).catch(() => window.location.assign('/login'));
          return;
        }
        if (data.type === 'operation.updated' || data.type === 'operation.completed') {
          const operation = data.operation;
          if (!operation) return;
          setOperations((current) => [operation, ...current.filter((item) => item.id !== operation.id)]);
          const operationFailed = operation.status === 'ERRO' || Number(operation.dados_adicionais?.falha || operation.dados_adicionais?.falhas || operation.dados_adicionais?.erro || 0) > 0;
          if (TERMINAL.has(operation.status) && !terminalToastIdsRef.current.has(operation.id)) {
            terminalToastIdsRef.current.add(operation.id);
            loadCenter();
            if (document.visibilityState === 'visible') {
              toast[operationFailed ? 'error' : 'success'](
                operationFailed ? 'Um processo terminou com falhas.' : 'Um processo foi concluído.',
                { description: operation.titulo },
              );
            }
            if (
              browserEnabled &&
              browserPermission === 'granted' &&
              document.visibilityState === 'hidden' &&
              'Notification' in window
            ) {
              new Notification(operationFailed ? 'Processo concluído com falhas' : 'Processo concluído', {
                body: operation.titulo,
                tag: 'operation-' + operation.id,
              });
            }
          }
        } else if (data.type === 'notification.created' && data.notification) {
          setNotifications((current) => [data.notification, ...current.filter((item) => item.id !== data.notification.id)]);
          loadCenter();
        } else if (data.event_type && !data.notification) {
          toast.info(data.message || 'Você recebeu uma nova notificação.');
          loadCenter();
        } else if (data.type === 'notification.created') {
          loadCenter();
        }
      } catch (error) {
        console.warn('Evento inválido na central de atividade:', error);
      }
    };
    source.onerror = () => {
      // EventSource reconnects automatically; polling keeps the saved view current meanwhile.
    };

    return () => {
      source.close();
      eventSourceRef.current = null;
    };
  }, [user, browserEnabled, browserPermission, loadCenter]);

  const activeOperations = useMemo(
    () => operations.filter((operation) => !TERMINAL.has(operation.status)),
    [operations],
  );
  const recentOperations = useMemo(
    () => operations.filter((operation) => TERMINAL.has(operation.status)),
    [operations],
  );
  const openRoute = async (route) => {
    if (route) {
      setOpen(false);
      navigate(route);
    }
  };
  const openOperation = (operation) => {
    setOpen(false);
    navigate(`/monitoramento/operacoes/minha-atividade?operation_id=${encodeURIComponent(operation.id)}`);
  };

  const markRead = async (notification) => {
    if (notification.lida || notification.read_at) return;
    try {
      const response = await fetch('/api/v2/notifications/' + notification.id + '/read', {
        method: 'PATCH',
        credentials: 'same-origin',
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || 'Falha ao atualizar aviso.');
      setNotifications((current) => current.map((item) => (
        item.id === notification.id ? { ...item, lida: true, read_at: new Date().toISOString() } : item
      )));
      setUnreadCount((current) => Math.max(0, current - 1));
    } catch {
      toast.error('Não foi possível marcar a notificação como lida.');
    }
  };

  const enableBrowserNotifications = async () => {
    if (!('Notification' in window)) return;
    const permission = await Notification.requestPermission();
    setBrowserPermission(permission);
    const enabled = permission === 'granted';
    setBrowserEnabled(enabled);
    localStorage.setItem(BROWSER_PREF_KEY, String(enabled));
    if (enabled) toast.success('Avisos do navegador ativados.');
  };

  const toggleBrowserNotifications = () => {
    if (browserEnabled) {
      setBrowserEnabled(false);
      localStorage.removeItem(BROWSER_PREF_KEY);
      return;
    }
    enableBrowserNotifications();
  };

  if (!user) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label="Abrir central de atividade">
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-primary-foreground">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
          {activeOperations.length > 0 && (
            <span className="absolute bottom-2 right-2 h-2 w-2 rounded-full border border-card bg-brand-aqua" aria-hidden="true" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={10} className="w-[calc(100vw-1rem)] max-w-[460px] p-0">
        <div className="border-b border-border/80 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-foreground">Central de atividade</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {activeOperations.length
                  ? activeOperations.length + ' processo(s) em andamento'
                  : 'Acompanhe seus processos e avisos'}
              </p>
            </div>
            {loadError && (
              <Button variant="ghost" size="icon" aria-label="Tentar sincronizar" onClick={loadCenter}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        <Tabs value={tab} onValueChange={setTab} className="p-3">
          <TabsList className="grid h-9 w-full grid-cols-2">
            <TabsTrigger value="processos">Processos{activeOperations.length > 0 ? ' (' + activeOperations.length + ')' : ''}</TabsTrigger>
            <TabsTrigger value="recentes">Recentes{unreadCount > 0 ? ' (' + unreadCount + ')' : ''}</TabsTrigger>
          </TabsList>

          <TabsContent value="processos" className="mt-3">
            <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
              {loading && operations.length === 0 ? (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                  <LoaderCircle className="h-4 w-4 animate-spin" /> Carregando atividade…
                </div>
              ) : activeOperations.length === 0 ? (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  Nenhum processo em andamento.
                </div>
              ) : activeOperations.map((operation) => (
                <OperationRow key={operation.id} operation={operation} onOpen={openOperation} />
              ))}
            </div>
          </TabsContent>

          <TabsContent value="recentes" className="mt-3">
            <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
              {recentOperations.map((operation) => (
                <OperationRow key={operation.id} operation={operation} onOpen={openOperation} />
              ))}
              {notifications.map((notification) => {
                const route = notification.dados_adicionais?.rota_destino;
                const read = notification.lida || !!notification.read_at;
                const Icon = notification.tipo === 'erro' ? CircleX : Info;
                return (
                  <div key={'notification-' + notification.id} className={'rounded-lg border p-3 ' + (read ? 'border-border/70 bg-card' : 'border-primary/20 bg-primary/5')}>
                    <div className="flex items-start gap-3">
                      <Icon className={'mt-0.5 h-4 w-4 shrink-0 ' + (notification.tipo === 'erro' ? 'text-destructive' : 'text-primary')} aria-hidden="true" />
                      <div className="min-w-0 flex-1">
                        <button type="button" onClick={() => { markRead(notification); openRoute(route); }} className="text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                          <span className="block text-sm font-semibold">{notification.titulo}</span>
                          <span className="mt-1 block text-sm text-muted-foreground">{notification.mensagem}</span>
                        </button>
                        <span className="mt-2 block text-xs text-muted-foreground">{formatTime(notification.created_at || notification.data_envio)}</span>
                        {route && (
                          <Button variant="link" size="sm" className="mt-1 h-auto px-0" onClick={() => { markRead(notification); openRoute(route); }}>
                            Abrir item relacionado
                          </Button>
                        )}
                      </div>
                      {!read && (
                        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" aria-label="Marcar como lida" onClick={() => markRead(notification)}>
                          <CheckCheck className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
              {!recentOperations.length && !notifications.length && (
                <div className="py-10 text-center text-sm text-muted-foreground">Nenhuma notificação recente.</div>
              )}
            </div>
          </TabsContent>
        </Tabs>

        {loadError && (
          <div role="status" className="mx-3 mb-3 rounded-md border border-warning/30 bg-warning-soft p-2 text-xs text-warning">
            Sem conexão com a central. Os dados salvos serão atualizados quando a conexão voltar.
          </div>
        )}

        <div className="border-t border-border/80 px-4 py-2">
          <Button variant="link" className="h-auto px-0 text-sm" onClick={() => { setOpen(false); navigate('/monitoramento/operacoes/minha-atividade'); }}>
            Abrir Minha atividade
          </Button>
        </div>

        {browserPermission !== 'unsupported' && (
          <div className="flex items-center justify-between border-t border-border/80 px-4 py-3">
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              {browserEnabled ? <Bell className="h-4 w-4 text-primary" /> : <BellOff className="h-4 w-4" />}
              Avisos do navegador
            </span>
            {browserPermission === 'denied' ? (
              <span className="text-xs text-muted-foreground">Bloqueados no navegador</span>
            ) : (
              <Button variant="outline" size="sm" onClick={toggleBrowserNotifications}>
                {browserEnabled ? 'Desativar' : 'Ativar'}
              </Button>
            )}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
