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
  HardDrive,
  Info,
  PlayCircle,
  RefreshCw,
  Search,
  Settings,
  XCircle,
  Zap
} from 'lucide-react';
import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Task Control Center
 * 
 * Centralized dashboard for Celery task management.
 * Consolidates scheduling, execution monitoring, and queue visualization.
 */
function TaskControlCenter() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('schedules');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  
  // Schedules State
  const [scheduledTasks, setScheduledTasks] = useState({});
  const [localFrequencies, setLocalFrequencies] = useState({});
  const [showReloadWarning, setShowReloadWarning] = useState(false);
  
  // Execution Logs State
  const [logs, setLogs] = useState([]);
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
    task_type: ''
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
        Object.entries(data.data || {}).forEach(([name, config]) => {
          freqs[name] = config.schedule_seconds;
        });
        setLocalFrequencies(freqs);
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
    } catch (e) {
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
    } catch (e) {
      toast.error('Erro ao salvar frequência');
    } finally {
      setSaving(false);
    }
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

  const handleReloadWorker = async () => {
    setReloading(true);
    try {
      const response = await fetch('/api/v2/admin/task-schedules/reload', { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
        setShowReloadWarning(false);
      }
    } catch (e) {
      toast.error('Erro ao solicitar recarga');
    } finally {
      setReloading(false);
    }
  };

  // --- API Calls for Logs ---

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (logFilters.status !== 'all') params.append('status', logFilters.status);
      if (logFilters.task_name) params.append('task_name', logFilters.task_name);
      if (logFilters.task_type) params.append('task_type', logFilters.task_type);
      params.append('limit', '50');

      const response = await fetch(`/api/v2/tasks/execution-logs?${params.toString()}`);
      const data = await response.json();
      if (data.success) setLogs(data.data || []);
    } catch (e) {
      toast.error('Erro ao carregar logs');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/v2/tasks/stats');
      const data = await response.json();
      if (data.success) setStats(data.stats);
    } catch (e) {}
  };

  const handleRetryTask = async (taskId) => {
    try {
      const response = await fetch(`/api/v2/tasks/execution-logs/${taskId}/retry`, { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        toast.success('Tarefa reenviada');
        fetchLogs();
        fetchStats();
      }
    } catch (e) {
      toast.error('Erro ao reenviar tarefa');
    }
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
    } catch (e) {
      toast.error('Erro ao reprocessar eventos');
    } finally {
      setReprocessing(false);
    }
  };

  const handleReprocessFila = async () => {
    setReprocessing(true);
    try {
      const response = await fetch('/api/v2/tasks/stock/reprocess-fila', { method: 'POST' });
      const data = await response.json();
      if (data.success) {
        toast.success(`Fila reprocessada: ${JSON.stringify(data.stats)}`);
        fetchLogs();
        fetchStats();
      }
    } catch (e) {
      toast.error('Erro ao reprocessar fila');
    } finally {
      setReprocessing(false);
    }
  };

  const confirmReprocess = (action) => {
    const messages = {
      'events': 'Isso irá reprocessar até 50 eventos não processados. Deseja continuar?',
      'fila': 'Isso irá reprocessar até 50 itens da fila de processamento de estoque. Deseja continuar?'
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
    if (confirmDialog.action === 'fila') handleReprocessFila();
  };

  // --- Unified Refresh ---
  const refreshAll = () => {
    if (activeTab === 'schedules') fetchSchedules();
    if (activeTab === 'logs') {
      fetchLogs();
      fetchStats();
    }
  };

  useEffect(() => {
    refreshAll();
    // Cleanup timers on unmount
    return () => {
      Object.values(debounceTimers.current).forEach(clearTimeout);
    };
  }, [activeTab, logFilters]);

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
      'processar-eventos-producao-periodic': 'Motor de Produção e Estoque',
      'renew-shopee-tokens': 'Renovação de Tokens Shopee',
      'drain-bling-webhook-failures': 'Recuperação de Falhas Bling'
    };
    return names[name] || name;
  };

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
            Gerenciamento e monitoramento de tarefas em segundo plano (Celery)
          </p>
        </div>
        <div className="flex gap-2">
          {showReloadWarning && (
            <Button variant="destructive" onClick={handleReloadWorker} disabled={reloading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${reloading ? 'animate-spin' : ''}`} />
              Aplicar Mudanças (Reiniciar Worker)
            </Button>
          )}
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="schedules">
            <Clock className="w-4 h-4 mr-2" /> Agendamentos
          </TabsTrigger>
          <TabsTrigger value="logs">
            <Activity className="w-4 h-4 mr-2" /> Histórico de Execução
          </TabsTrigger>
          <TabsTrigger value="queue">
            <Zap className="w-4 h-4 mr-2" /> Fila em Tempo Real
          </TabsTrigger>
        </TabsList>

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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
              <Button size="sm" variant="outline" onClick={() => confirmReprocess('fila')} disabled={reprocessing}>
                <AlertTriangle className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} /> Fila
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
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          {log.status === 'FAILED' && (
                            <Button size="sm" variant="ghost" onClick={() => handleRetryTask(log.id)}>
                              <PlayCircle className="h-4 w-4 mr-1" /> Reenviar
                            </Button>
                          )}
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
      </Tabs>

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
