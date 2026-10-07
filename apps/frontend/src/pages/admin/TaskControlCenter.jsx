import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import QueueMonitor from '@/components/admin/QueueMonitor';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Info,
  RefreshCw,
  Search,
  Settings,
  XCircle,
  Zap
} from 'lucide-react';
import { useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import FerramentasPage from './FerramentasPage';

/**
 * Converte o cron gravado no banco para o valor de um <input type="time">.
 *
 * A tela edita apenas o caso diario ("todo dia as HH:MM"), que e o unico que
 * alguem configura pela interface. Cron com dia da semana ou intervalo dentro
 * da hora continua valido no backend, mas aparece aqui como somente leitura —
 * degradar para um campo de horario perderia a configuracao ao salvar.
 */
function cronParaHorario(cron) {
  if (!cron || typeof cron !== 'object') return '';
  const { hour, minute, day_of_week, day_of_month, month_of_year } = cron;
  const restritivo = [day_of_week, day_of_month, month_of_year].some(
    (campo) => campo != null && String(campo) !== '*',
  );
  if (restritivo) return '';
  if (hour == null || String(hour).includes('*') || String(hour).includes('/')) return '';
  const h = String(hour).padStart(2, '0');
  const m = String(minute ?? 0).padStart(2, '0');
  if (Number.isNaN(Number(h)) || Number.isNaN(Number(m))) return '';
  return `${h}:${m}`;
}

function descreverCron(cron) {
  const horario = cronParaHorario(cron);
  if (horario) return `todo dia as ${horario}`;
  if (!cron) return '-';
  const campos = ['minute', 'hour', 'day_of_month', 'month_of_year', 'day_of_week'];
  return `cron ${campos.map((campo) => cron[campo] ?? '*').join(' ')}`;
}

/**
 * Task Control Center
 * 
 * Centralized dashboard for Celery task management.
 * Consolidates scheduling, execution monitoring, and queue visualization.
 */
function TaskControlCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = ['overview', 'schedules', 'logs', 'queue', 'maintenance'].includes(searchParams.get('aba')) ? searchParams.get('aba') : 'overview';
  const [activeTab, setActiveTab] = useState(tabFromUrl);
  useEffect(() => { setActiveTab(tabFromUrl); }, [tabFromUrl]);
  const changeTab = (value) => {
    setActiveTab(value);
    setSearchParams((current) => { const next = new URLSearchParams(current); next.set('aba', value); return next; });
  };
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  
  // Schedules State
  const [scheduledTasks, setScheduledTasks] = useState({});
  const [localFrequencies, setLocalFrequencies] = useState({});
  const [localCrons, setLocalCrons] = useState({});
  const [showReloadWarning, setShowReloadWarning] = useState(false);
  
  // Execution Logs State
  const [logs, setLogs] = useState([]);
  const [overview, setOverview] = useState(null);
  const [hours, setHours] = useState(24);
  const [selectedExecution, setSelectedExecution] = useState(null);
  const [stats, setStats] = useState({
    total: 0,
    pending: 0,
    processing: 0,
    completed: 0,
    failed: 0,
    cancelled: 0
  });
  
  // Filters for Logs
  const [logFilters, setLogFilters] = useState({
    status: 'all',
    task_name: '',
    task_type: '',
    integration_id: '',
    origin: '',
    order_id: '',
    batch_id: '',
  });

  const [confirmDialog, setConfirmDialog] = useState({ open: false, action: null, message: '' });
  
  // Refs for debouncing
  const debounceTimers = useRef({});

  // --- API Calls for Schedules ---

  const fetchSchedules = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/admin/task-schedules');
      const data = await response.json();
      if (data.success) {
        setScheduledTasks(data.data || {});
        // Inicializa frequências locais para edição fluida
        const freqs = {};
        const crons = {};
        Object.entries(data.data || {}).forEach(([name, config]) => {
          freqs[name] = config.schedule_seconds;
          crons[name] = cronParaHorario(config.cron);
        });
        setLocalFrequencies(freqs);
        setLocalCrons(crons);
      }
    } catch (e) {
      console.error('Erro ao carregar agendamentos:', e);
      toast.error('Erro ao carregar agendamentos');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleTask = async (taskName, currentEnabled) => {
    setSaving(true);
    try {
      const response = await fetch(`/api/v2/admin/task-schedules/${taskName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !currentEnabled })
      });
      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
        if (data.warning) setShowReloadWarning(true);
        // Atualiza apenas o estado local para evitar re-render total
        setScheduledTasks(prev => ({
          ...prev,
          [taskName]: { ...prev[taskName], enabled: !currentEnabled }
        }));
      }
    } catch {
      toast.error('Erro ao atualizar tarefa');
    } finally {
      setSaving(false);
    }
  };

  const saveFrequency = async (taskName, newFrequency) => {
    setSaving(true);
    try {
      const response = await fetch(`/api/v2/admin/task-schedules/${taskName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schedule_seconds: parseInt(newFrequency) })
      });
      const data = await response.json();
      if (data.success) {
        toast.success(`Frequência de ${getTaskFriendlyName(taskName)} atualizada`);
        if (data.warning) setShowReloadWarning(true);
        // Sincroniza o estado principal
        setScheduledTasks(prev => ({
          ...prev,
          [taskName]: { ...prev[taskName], schedule_seconds: parseInt(newFrequency) }
        }));
      }
    } catch {
      toast.error('Erro ao salvar frequência');
    } finally {
      setSaving(false);
    }
  };

  const saveCron = async (taskName, horario) => {
    // Campo vazio devolve a task ao modo intervalo: o backend interpreta
    // cron: null como "remover o horario" e volta a usar schedule_seconds.
    const cron = horario
      ? { hour: Number(horario.split(':')[0]), minute: Number(horario.split(':')[1]) }
      : null;
    setSaving(true);
    try {
      const response = await fetch(`/api/v2/admin/task-schedules/${taskName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cron })
      });
      const data = await response.json();
      if (!data.success) {
        toast.error(data.error || 'Erro ao salvar horario');
        return;
      }
      toast.success(
        cron
          ? `${getTaskFriendlyName(taskName)} agendada para ${horario}`
          : `${getTaskFriendlyName(taskName)} voltou ao modo intervalo`,
      );
      if (data.warning) setShowReloadWarning(true);
      setScheduledTasks(prev => ({
        ...prev,
        [taskName]: { ...prev[taskName], cron: cron || undefined }
      }));
    } catch {
      toast.error('Erro ao salvar horario');
    } finally {
      setSaving(false);
    }
  };

  const handleCronChange = (taskName, value) => {
    setLocalCrons(prev => ({ ...prev, [taskName]: value }));

    const chave = `cron:${taskName}`;
    if (debounceTimers.current[chave]) clearTimeout(debounceTimers.current[chave]);
    debounceTimers.current[chave] = setTimeout(() => saveCron(taskName, value), 1000);
  };

  const handleFrequencyChange = (taskName, value) => {
    // 1. Atualiza o estado local imediatamente (UI rápida)
    setLocalFrequencies(prev => ({ ...prev, [taskName]: value }));
    
    // 2. Debounce para salvar no banco apenas após parar de digitar
    if (debounceTimers.current[taskName]) {
      clearTimeout(debounceTimers.current[taskName]);
    }
    
    debounceTimers.current[taskName] = setTimeout(() => {
      if (value && parseInt(value) > 0) {
        saveFrequency(taskName, value);
      }
    }, 1000); // 1 segundo de delay
  };

  const fetchOverview = async () => {
    try {
      const response = await fetch(`/api/v2/admin/task-center/overview?hours=${hours}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao medir a saúde');
      setOverview(body.data);
      setStats({ total: body.data.task_sample_size, pending: body.data.task_stats.PENDING,
        processing: body.data.task_stats.PROCESSING, completed: body.data.task_stats.COMPLETED,
        failed: body.data.task_stats.FAILED, cancelled: body.data.task_stats.CANCELLED });
    } catch (error) {
      setOverview({ status: 'unavailable', error: error.message });
    }
  };

  const fetchCenterSchedules = async () => {
    const response = await fetch('/api/v2/admin/task-center/schedules');
    const body = await response.json();
    if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao carregar agendamentos');
    setShowReloadWarning(body.data.restart_state === 'pending');
  };

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ hours: String(hours), limit: '100', offset: '0' });
      if (logFilters.status !== 'all') params.append('status', logFilters.status);
      if (logFilters.task_name) params.append('task_name', logFilters.task_name);
      if (logFilters.task_type) params.append('task_type', logFilters.task_type);
      if (logFilters.integration_id) params.append('integration_id', logFilters.integration_id);
      if (logFilters.origin) params.append('origin', logFilters.origin);
      if (logFilters.order_id) params.append('order_id', logFilters.order_id);
      if (logFilters.batch_id) params.append('batch_id', logFilters.batch_id);
      params.append('limit', '50');

      const response = await fetch(`/api/v2/admin/task-center/executions?${params.toString()}`);
      const data = await response.json();
      if (data.success) setLogs(data.data || []);
    } catch {
      toast.error('Erro ao carregar logs');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    await fetchOverview();
  };

  const openExecution = async log => {
    try {
      const response = await fetch(`/api/v2/admin/task-center/executions/${encodeURIComponent(String(log.id).replace(/^task-/, ''))}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao abrir detalhes');
      setSelectedExecution(body.data);
    } catch (error) { toast.error(error.message); }
  };

  const handleReprocessEvents = async () => {
    setReprocessing(true);
    try {
      const response = await fetch('/api/v2/tasks/stock/reprocess-events', { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        toast.success(`Eventos reprocessados: ${JSON.stringify(data.stats)}`);
        fetchLogs();
        fetchStats();
      }
    } catch {
      toast.error('Erro ao reprocessar eventos');
    } finally {
      setReprocessing(false);
    }
  };

  const confirmReprocess = (action) => {
    const messages = {
      'events': 'Isso irá reprocessar até 50 eventos não processados. Deseja continuar?'
    };
    setConfirmDialog({
      open: true,
      action,
      message: messages[action]
    });
  };

  const executeConfirmedAction = () => {
    setConfirmDialog({ ...confirmDialog, open: false });
    if (confirmDialog.action === 'events') handleReprocessEvents();
  };

  // --- Unified Refresh ---
  const refreshAll = () => {
    fetchOverview();
    if (activeTab === 'schedules') { fetchSchedules(); fetchCenterSchedules().catch(error => toast.error(error.message)); }
    if (activeTab === 'logs') fetchLogs();
    if (activeTab === 'queue') fetchCenterSchedules().catch(() => {});
  };

  useEffect(() => {
    refreshAll();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') refreshAll();
    }, 30000);
    return () => {
      clearInterval(timer);
      Object.values(debounceTimers.current).forEach(clearTimeout);
    };
  }, [activeTab, logFilters, hours]);

  // --- Helpers ---
  const formatFrequency = (seconds) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}min`;
    return `${Math.floor(seconds / 3600)}h`;
  };

  const getTaskFriendlyName = (name) => {
    const names = {
      'sync-firestore-tokens': 'Sincronização de Tokens (Firestore)',
      'consumir-fila-bling': 'Consumir Fila Bling (Webhooks)',
      'consumir-fila-shopee': 'Consumir Fila Shopee (Webhooks)',
      'consumir-fila-mercadolivre': 'Consumir Fila Mercado Livre (Webhooks)',
      'processar-eventos-producao-periodic': 'Motor de Produção e Estoque',
      'renew-shopee-tokens': 'Renovação de Tokens Shopee',
      'drain-bling-webhook-failures': 'Recuperação de Falhas Bling',
      'processar-personalizados-diario': 'Extração de Personalizados (lote diário)',
      'recolher-lotes-ia-parados': 'Recuperação de Lotes de IA Parados'
    };
    return names[name] || name;
  };

  const scheduleRows = Object.entries(scheduledTasks)
    .map(([taskName, config]) => ({ taskName, ...config }))
    .sort((a, b) => getTaskFriendlyName(a.taskName).localeCompare(getTaskFriendlyName(b.taskName)));

  const getStatusBadge = (status) => {
    const badges = {
      'PENDING': <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200"><Clock className="h-3 w-3 mr-1" /> Pendente</Badge>,
      'PROCESSING': <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200"><Activity className="h-3 w-3 mr-1" /> Processando</Badge>,
      'COMPLETED': <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="h-3 w-3 mr-1" /> Concluído</Badge>,
      'FAILED': <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200"><XCircle className="h-3 w-3 mr-1" /> Falhou</Badge>,
      'CANCELLED': <Badge variant="outline" className="bg-gray-50 text-gray-700 border-gray-200"><XCircle className="h-3 w-3 mr-1" /> Cancelado</Badge>
    };
    return badges[status] || <Badge variant="outline">{status}</Badge>;
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header Unificado */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Settings className="h-8 w-8 text-primary" /> Central de Operações
          </h1>
          <p className="text-muted-foreground mt-1">
            Execuções, filas, workers compartilhados e agendamentos do backend
          </p>
        </div>
        <div className="flex gap-2">
          {showReloadWarning && <Badge variant="outline" className="border-amber-400 bg-amber-50 text-amber-800">Worker precisa ser reiniciado manualmente</Badge>}
          <select value={hours} onChange={event => setHours(Number(event.target.value))} className="h-9 rounded border bg-background px-2 text-sm">
            <option value={24}>Últimas 24 horas</option><option value={72}>Últimos 3 dias</option><option value={168}>Últimos 7 dias</option>
          </select>
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={changeTab} className="w-full">
        <TabsList className="grid w-full grid-cols-2 sm:grid-cols-5">
          <TabsTrigger value="overview"><Activity className="w-4 h-4 mr-2" /> Visão geral</TabsTrigger>
          <TabsTrigger value="schedules">
            <Clock className="w-4 h-4 mr-2" /> Agendamentos
          </TabsTrigger>
          <TabsTrigger value="logs">
            <Activity className="w-4 h-4 mr-2" /> Execuções
          </TabsTrigger>
          <TabsTrigger value="queue">
            <Zap className="w-4 h-4 mr-2" /> Fila em Tempo Real
          </TabsTrigger>
          <TabsTrigger value="maintenance"><Settings className="w-4 h-4 mr-2" />Manutenção</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4 mt-6">
          {!overview || overview.status === 'unavailable' ? <Card className="border-red-300"><CardContent className="p-5 text-sm text-red-800">Saúde indisponível: {overview?.error || 'consultando serviços'}</CardContent></Card> : <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <StatCard title={`Execuções recentes (${hours}h, amostra)`} value={overview.task_sample_size} color="gray" />
              <StatCard title="Em processamento" value={overview.task_stats.PROCESSING} color="blue" />
              <StatCard title="Falhas no período" value={overview.task_stats.FAILED} color={overview.task_stats.FAILED ? 'red' : 'green'} />
              <StatCard title="Pendentes" value={overview.task_stats.PENDING} color="yellow" />
              <StatCard title="Sinal medido em" value={new Date(overview.measured_at).toLocaleTimeString('pt-BR')} color="gray" />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><CardHeader><CardTitle>Filas</CardTitle><CardDescription>Tamanho atual informado por cada serviço.</CardDescription></CardHeader><CardContent className="space-y-3">
                {Object.entries(overview.queues || {}).map(([name, section]) => <div key={name} className="rounded border p-3">
                  <div className="flex justify-between"><strong className="capitalize">{name.replaceAll('_', ' ')}</strong><Badge variant="outline" className={section.status === 'available' ? 'text-green-700' : 'text-red-700'}>{section.status === 'available' ? 'Normal' : 'Indisponível'}</Badge></div>
                  {section.status === 'available' ? <pre className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(section.queues, null, 2)}</pre> : <p className="mt-2 text-xs text-red-700">{section.reason}</p>}
                </div>)}
              </CardContent></Card>
              <Card><CardHeader><CardTitle>Workers e funções</CardTitle><CardDescription>Atividade dos consumidores compartilhados e das tarefas Celery.</CardDescription></CardHeader><CardContent className="space-y-2">
                {overview.processes?.status !== 'available' ? <p className="rounded border border-red-300 p-3 text-sm text-red-700">Indisponível: {overview.processes?.reason || 'sem dados'}</p> : overview.processes.items.map(process => <div key={process.name} className="flex flex-wrap items-center justify-between gap-2 rounded border p-3 text-sm"><span>{process.name}{process.active_tasks ? ` · ${process.active_tasks} execução(ões) ativa(s)` : ''}{process.stale_tasks ? ` · ${process.stale_tasks} sem progresso há 15 min` : ''}</span><span className={process.status === 'normal' ? 'text-green-700' : process.status === 'attention' ? 'text-amber-700' : 'text-red-700'}>{process.status === 'normal' ? 'Normal' : process.status === 'attention' ? 'Atenção' : 'Indisponível'}{process.last_heartbeat ? ` · ${new Date(process.last_heartbeat).toLocaleTimeString('pt-BR')}` : ''}</span></div>)}
              </CardContent></Card>
            </div>
            <Card><CardHeader><CardTitle>Mercado Livre por conta</CardTitle><CardDescription>Pendências de mensagem, falhas e resultados que aguardam revisão.</CardDescription></CardHeader><CardContent>
              {overview.mercadolivre_status !== 'available' ? <p className="rounded border border-red-300 p-3 text-sm text-red-700">Sem dados: {overview.mercadolivre_error || 'falha ao consultar as contas'}</p> : overview.mercadolivre.length ? <div className="space-y-2">{overview.mercadolivre.map(account => <details key={account.integration_id} className="rounded border p-3 text-sm"><summary className="cursor-pointer"><strong>{account.name}</strong><span className="ml-3">{account.health.inbox_pending} mensagens pendentes · {account.health.inbox_failed} falhas · {account.health.incomplete_conversations} conversas incompletas · {account.health.waiting_review} revisões · {account.health.ai_errors} falhas de IA{account.health.oldest_pending_at ? ` · pendência desde ${new Date(account.health.oldest_pending_at).toLocaleString('pt-BR')}` : ''}</span></summary><div className="mt-3 space-y-3">{!!account.pending_conversations.length && <div><strong>Conversas aguardando associação</strong>{account.pending_conversations.map(row => <p key={row.pack_id} className="mt-1 text-xs">Pacote {row.pack_id} · pedidos {row.pending_order_ids.join(', ') || 'aguardando importação'} · {row.message_count} mensagem(ns) · última {row.last_message_at ? new Date(row.last_message_at).toLocaleString('pt-BR') : '—'}</p>)}</div>}{!!account.unmatched_notifications.length && <div><strong>Notificações sem conta confirmada</strong>{account.unmatched_notifications.map((row, index) => <p key={`${row.provider_message_id}-${index}`} className="mt-1 text-xs">Mensagem {row.provider_message_id} · vendedor {row.account_user_id || 'ausente'} · aplicativo {row.application_id || 'ausente'} · {row.last_error || row.status}</p>)}</div>}{!account.pending_conversations.length && !account.unmatched_notifications.length && <p className="text-xs text-muted-foreground">Sem conversas sem associação nem notificações pendentes.</p>}</div></details>)}</div> : <p className="text-sm text-muted-foreground">Nenhuma conta Mercado Livre conectada.</p>}
            </CardContent></Card>
            <Card><CardHeader><CardTitle>Shopee por conta</CardTitle><CardDescription>Completude das conversas atendidas pelos consumidores atuais de chat.</CardDescription></CardHeader><CardContent>
              {overview.shopee_status !== 'available' ? <p className="rounded border border-red-300 p-3 text-sm text-red-700">Sem dados: {overview.shopee_error || 'falha ao consultar as contas'}</p> : overview.shopee?.length ? <div className="space-y-2">{overview.shopee.map(account => <div key={account.integration_id} className="rounded border p-3 text-sm"><strong>{account.name}</strong><span className="ml-3">{account.health.incomplete_conversations} conversas pendentes · {account.health.failed_conversations} falhas · {account.health.expired_conversations} expiradas</span>{account.health.oldest_pending_at && <p className="mt-1 text-xs text-muted-foreground">Pendência mais antiga desde {new Date(account.health.oldest_pending_at).toLocaleString('pt-BR')}</p>}</div>)}</div> : <p className="text-sm text-muted-foreground">Nenhuma conta Shopee conectada.</p>}
            </CardContent></Card>
            {!!overview.recent_failures?.length && <Card className="border-red-200"><CardHeader><CardTitle>Falhas recentes</CardTitle></CardHeader><CardContent className="space-y-2">{overview.recent_failures.map(row => <div key={row.id} className="rounded border p-3 text-sm"><strong>{row.task_name}</strong> · {row.marketplace_integration_id ? `Conta ${row.marketplace_integration_id}` : 'Tarefa geral'}<p className="mt-1 text-red-700">{row.error_message || 'Falha sem detalhe registrado'}</p></div>)}</CardContent></Card>}
          </>}
        </TabsContent>

        {/* --- Aba 1: Agendamentos --- */}
        <TabsContent value="schedules" className="space-y-4 mt-6">
          {showReloadWarning && (
            <Card className="border-yellow-400 bg-yellow-50">
              <CardContent className="p-4 flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
                <div className="flex-1">
                  <p className="font-medium text-yellow-900">Atenção: Mudanças pendentes</p>
                  <p className="text-sm text-yellow-700">Algumas tarefas tiveram sua frequência alterada. Clique em "Aplicar Mudanças" no topo para efetivar.</p>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-3">
              <CardTitle>Agendamentos do Worker</CardTitle>
              <CardDescription>Ative, desative e ajuste a frequencia das tasks periodicas do Celery.</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[90px]">Ativa</TableHead>
                    <TableHead>Tarefa</TableHead>
                    <TableHead className="w-[200px]">Frequencia / Horario</TableHead>
                    <TableHead className="hidden lg:table-cell">Task Celery</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                        Carregando agendamentos...
                      </TableCell>
                    </TableRow>
                  ) : scheduleRows.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                        Nenhum agendamento configurado.
                      </TableCell>
                    </TableRow>
                  ) : scheduleRows.map((config) => (
                    <TableRow key={config.taskName} className={!config.enabled ? 'bg-muted/30 text-muted-foreground' : ''}>
                      <TableCell>
                        <Switch
                          checked={config.enabled}
                          onCheckedChange={() => handleToggleTask(config.taskName, config.enabled)}
                          disabled={saving}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{getTaskFriendlyName(config.taskName)}</div>
                        <div className="text-xs text-muted-foreground">{config.description || config.taskName}</div>
                        <div className="text-xs text-muted-foreground">Última: {config.last_execution?.started_at ? new Date(config.last_execution.started_at).toLocaleString('pt-BR') : 'sem registro'} · último sucesso: {config.last_success?.finished_at ? new Date(config.last_success.finished_at).toLocaleString('pt-BR') : 'sem registro'}</div>
                      </TableCell>
                      <TableCell>
                        {/* Intervalo e horario sao mutuamente excludentes no
                            beat. Os dois campos ficam visiveis para deixar a
                            troca obvia, mas o inativo fica desabilitado: e o
                            proprio controle que informa qual regra vale. */}
                        <div className="space-y-1.5">
                          <div className="flex items-center gap-2">
                            <Input
                              type="number"
                              min="1"
                              value={localFrequencies[config.taskName] || ''}
                              onChange={(e) => handleFrequencyChange(config.taskName, e.target.value)}
                              disabled={saving || !config.enabled || Boolean(config.cron)}
                              className="h-8 w-20"
                              title="Intervalo em segundos"
                            />
                            <span className="w-14 text-xs text-muted-foreground">
                              {config.cron ? '—' : formatFrequency(localFrequencies[config.taskName])}
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Clock className="h-3 w-3 text-muted-foreground" />
                            <Input
                              type="time"
                              value={localCrons[config.taskName] || ''}
                              onChange={(e) => handleCronChange(config.taskName, e.target.value)}
                              disabled={saving || !config.enabled || (Boolean(config.cron) && !cronParaHorario(config.cron))}
                              className="h-8 w-24"
                              title="Horario fixo diario (vazio = usar intervalo)"
                            />
                          </div>
                          {config.cron && !cronParaHorario(config.cron) && (
                            <div className="text-xs text-muted-foreground">
                              {descreverCron(config.cron)}
                            </div>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell">
                        <code className="rounded bg-muted px-2 py-1 text-xs">
                          {config.task_name || config.taskName}
                        </code>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <div className="hidden" aria-hidden="true">
            {Object.entries(scheduledTasks).map(([taskName, config]) => (
              <Card key={taskName} className={!config.enabled ? 'opacity-70 grayscale-[0.5]' : ''}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-lg">{getTaskFriendlyName(taskName)}</CardTitle>
                      <CardDescription className="text-xs font-mono">{taskName}</CardDescription>
                    </div>
                    <Switch
                      checked={config.enabled}
                      onCheckedChange={() => handleToggleTask(taskName, config.enabled)}
                      disabled={saving}
                    />
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">{config.description}</p>
                  <div className="flex items-center gap-4">
                    <div className="flex-1">
                      <label className="text-xs font-medium mb-1 block">Frequência (segundos)</label>
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          min="1"
                          value={localFrequencies[taskName] || ''}
                          onChange={(e) => handleFrequencyChange(taskName, e.target.value)}
                          disabled={saving || !config.enabled}
                          className="w-24 h-8"
                        />
                        <span className="text-xs text-muted-foreground">
                          {formatFrequency(localFrequencies[taskName])}
                        </span>
                        {saving && debounceTimers.current[taskName] && (
                          <RefreshCw className="h-3 w-3 animate-spin text-primary" />
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* --- Aba 2: Histórico --- */}
        <TabsContent value="logs" className="space-y-4 mt-6">
          <div className="flex justify-between items-end gap-4">
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4 flex-1">
              <StatCard title="Total" value={stats.total} color="gray" />
              <StatCard title="Pendentes" value={stats.pending} color="yellow" />
              <StatCard title="Processando" value={stats.processing} color="blue" />
              <StatCard title="Concluídos" value={stats.completed} color="green" />
              <StatCard title="Falharam" value={stats.failed} color="red" />
              <StatCard title="Cancelados" value={stats.cancelled} color="gray" />
            </div>
            <div className="flex flex-col gap-2">
              <Button size="sm" variant="outline" onClick={() => confirmReprocess('events')} disabled={reprocessing}>
                <Zap className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} /> Eventos
              </Button>
            </div>
          </div>

          {/* Filtros */}
          <Card>
            <CardContent className="p-4 flex flex-col md:flex-row gap-4">
              <div className="flex-1 relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Filtrar por nome..."
                  className="pl-8"
                  value={logFilters.task_name}
                  onChange={(e) => setLogFilters({...logFilters, task_name: e.target.value})}
                />
              </div>
              <select
                className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm w-full md:w-48"
                value={logFilters.status}
                onChange={(e) => setLogFilters({...logFilters, status: e.target.value})}
              >
                <option value="all">Todos os Status</option>
                <option value="PENDING">Pendente</option>
                <option value="PROCESSING">Processando</option>
                <option value="COMPLETED">Concluído</option>
                <option value="FAILED">Falhou</option>
              </select>
              <Input className="w-full md:w-36" type="number" min="1" placeholder="ID da conta" value={logFilters.integration_id} onChange={e => setLogFilters({...logFilters, integration_id: e.target.value})} />
              <select className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm w-full md:w-40" value={logFilters.origin} onChange={e => setLogFilters({...logFilters, origin: e.target.value})}><option value="">Todas as origens</option><option value="manual">Manual</option><option value="scheduled">Agendada</option><option value="recovery">Recuperação</option></select>
              <Input className="w-full md:w-36" placeholder="Pedido ID" value={logFilters.order_id} onChange={e => setLogFilters({...logFilters, order_id: e.target.value})} />
              <Input className="w-full md:w-36" placeholder="Lote ID" value={logFilters.batch_id} onChange={e => setLogFilters({...logFilters, batch_id: e.target.value})} />
            </CardContent>
          </Card>

          {/* Tabela de Logs */}
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Tarefa</TableHead>
                  <TableHead>Execução</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center py-10 text-muted-foreground">
                      Nenhum registro encontrado.
                    </TableCell>
                  </TableRow>
                ) : (
                  logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell>{getStatusBadge(log.status)}</TableCell>
                      <TableCell>
                        <div className="font-medium text-sm">{getTaskFriendlyName(log.task_name)}</div>
                        <div className="text-[10px] text-muted-foreground">{log.task_name}</div>
                      </TableCell>
                      <TableCell className="text-xs">
                        <div className="flex flex-col">
                          <span>Início: {new Date(log.started_at).toLocaleString('pt-BR')}</span>
                          {log.finished_at && <span>Fim: {new Date(log.finished_at).toLocaleString('pt-BR')}</span>}
                          <span>{log.duration_ms == null ? 'duração não registrada' : `${log.duration_ms} ms`} · {log.execution_origin || 'origem antiga'} · fila {log.queue_name || '—'} · conta {log.marketplace_integration_id || 'geral'}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => openExecution(log)}><Info className="h-4 w-4 mr-1" /> Detalhes</Button>
                          {log.error_message && (
                            <Button size="sm" variant="ghost" onClick={() => alert(log.error_message)}>
                              <AlertCircle className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        {/* --- Aba 3: Fila Redis --- */}
        <TabsContent value="queue" className="mt-6">
          <QueueMonitor embed />
        </TabsContent>
        <TabsContent value="maintenance" className="mt-6">
          <FerramentasPage embedded />
        </TabsContent>
      </Tabs>

      <AlertDialog open={Boolean(selectedExecution)} onOpenChange={open => !open && setSelectedExecution(null)}>
        <AlertDialogContent className="max-h-[85vh] overflow-y-auto"><AlertDialogHeader><AlertDialogTitle>{selectedExecution?.task_name || 'Detalhes da execução'}</AlertDialogTitle><AlertDialogDescription>Execução {selectedExecution?.id} · {selectedExecution?.execution_origin || 'origem não registrada'} · Conta {selectedExecution?.marketplace_integration_id || 'geral'} · Fila {selectedExecution?.queue_name || 'não registrada'} · {selectedExecution?.duration_ms ?? '—'} ms</AlertDialogDescription></AlertDialogHeader>
          <div className="space-y-3 text-sm"><div>Status: {selectedExecution?.status} · Início: {selectedExecution?.started_at ? new Date(selectedExecution.started_at).toLocaleString('pt-BR') : '—'} · Fim: {selectedExecution?.finished_at ? new Date(selectedExecution.finished_at).toLocaleString('pt-BR') : 'em andamento'}</div>{selectedExecution?.correlation_id && <div>Correlação: <code>{selectedExecution.correlation_id}</code></div>}{selectedExecution?.error_message && <p className="rounded bg-red-50 p-3 text-red-800">{selectedExecution.error_message}</p>}<pre className="max-h-72 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(selectedExecution?.metadata || {}, null, 2)}</pre></div>
          <AlertDialogFooter><AlertDialogCancel>Fechar</AlertDialogCancel></AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirmação de Reprocessamento */}
      <AlertDialog open={confirmDialog.open} onOpenChange={(open) => setConfirmDialog({ ...confirmDialog, open })}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar Reprocessamento</AlertDialogTitle>
            <AlertDialogDescription>{confirmDialog.message}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={executeConfirmedAction} disabled={reprocessing}>
              Confirmar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function StatCard({ title, value, color }) {
  const borderColors = {
    gray: 'border-l-gray-400',
    yellow: 'border-l-yellow-400',
    blue: 'border-l-blue-400',
    green: 'border-l-green-400',
    red: 'border-l-red-400'
  };
  return (
    <Card className={`p-3 border-l-4 ${borderColors[color]}`}>
      <p className="text-[10px] font-bold text-muted-foreground uppercase">{title}</p>
      <h3 className="text-lg font-bold">{value}</h3>
    </Card>
  );
}

export default TaskControlCenter;
