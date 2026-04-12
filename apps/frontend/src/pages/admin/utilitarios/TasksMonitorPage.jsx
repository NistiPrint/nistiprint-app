import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  HardDrive,
  PlayCircle,
  RefreshCw,
  Search,
  XCircle,
  Zap
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Tasks Monitor Page
 * 
 * Provides granular monitoring of Celery task executions with filtering,
 * retry, cancel, and detail viewing capabilities.
 */
function TasksMonitorPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState({ open: false, action: null, message: '' });
  const [tasks, setTasks] = useState([]);
  const [stats, setStats] = useState({
    total: 0,
    pending: 0,
    processing: 0,
    completed: 0,
    failed: 0,
    cancelled: 0
  });

  // Filters
  const [filters, setFilters] = useState({
    status: 'all',
    task_name: '',
    task_type: ''
  });

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.status !== 'all') params.append('status', filters.status);
      if (filters.task_name) params.append('task_name', filters.task_name);
      if (filters.task_type) params.append('task_type', filters.task_type);
      params.append('limit', '100');

      const response = await fetch(`/api/v2/tasks/execution-logs?${params.toString()}`);
      const data = await response.json();
      
      if (data.success) {
        setTasks(data.data || []);
      } else {
        toast.error('Erro ao carregar tarefas');
      }
    } catch (e) {
      console.error('Erro ao carregar tarefas:', e);
      toast.error('Erro ao carregar tarefas');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/v2/tasks/stats');
      const data = await response.json();
      
      if (data.success) {
        setStats(data.stats);
      }
    } catch (e) {
      console.error('Erro ao carregar estatísticas:', e);
    }
  };

  const handleRetry = async (taskId) => {
    try {
      const response = await fetch(`/api/v2/tasks/execution-logs/${taskId}/retry`, {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success('Tarefa reenviada para processamento');
        fetchTasks();
        fetchStats();
      } else {
        toast.error(data.error || 'Erro ao reenviar tarefa');
      }
    } catch (e) {
      console.error('Erro ao reenviar tarefa:', e);
      toast.error('Erro ao reenviar tarefa');
    }
  };

  const handleCancel = async (taskId) => {
    try {
      const response = await fetch(`/api/v2/tasks/execution-logs/${taskId}/cancel`, {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success('Tarefa cancelada com sucesso');
        fetchTasks();
        fetchStats();
      } else {
        toast.error(data.error || 'Erro ao cancelar tarefa');
      }
    } catch (e) {
      console.error('Erro ao cancelar tarefa:', e);
      toast.error('Erro ao cancelar tarefa');
    }
  };

  const handleReprocessEvents = async () => {
    setReprocessing(true);
    try {
      const response = await fetch('/api/v2/tasks/stock/reprocess-events', {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success(`Eventos reprocessados com sucesso: ${JSON.stringify(data.stats)}`);
        fetchTasks();
        fetchStats();
      } else {
        toast.error(data.error || 'Erro ao reprocessar eventos');
      }
    } catch (e) {
      console.error('Erro ao reprocessar eventos:', e);
      toast.error('Erro ao reprocessar eventos');
    } finally {
      setReprocessing(false);
    }
  };

  const handleReprocessFila = async () => {
    setReprocessing(true);
    try {
      const response = await fetch('/api/v2/tasks/stock/reprocess-fila', {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success(`Fila reprocessada com sucesso: ${JSON.stringify(data.stats)}`);
        fetchTasks();
        fetchStats();
      } else {
        toast.error(data.error || 'Erro ao reprocessar fila');
      }
    } catch (e) {
      console.error('Erro ao reprocessar fila:', e);
      toast.error('Erro ao reprocessar fila');
    } finally {
      setReprocessing(false);
    }
  };

  const confirmReprocess = (action) => {
    if (action === 'events') {
      setConfirmDialog({
        open: true,
        action: 'events',
        message: 'Isso irá reprocessar até 50 eventos não processados. Deseja continuar?'
      });
    } else if (action === 'fila') {
      setConfirmDialog({
        open: true,
        action: 'fila',
        message: 'Isso irá reprocessar até 50 itens da fila de processamento de estoque. Deseja continuar?'
      });
    }
  };

  const executeConfirmedAction = () => {
    setConfirmDialog({ open: false, action: null, message: '' });
    if (confirmDialog.action === 'events') {
      handleReprocessEvents();
    } else if (confirmDialog.action === 'fila') {
      handleReprocessFila();
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchStats();

    // Auto-refresh every 15 seconds
    const interval = setInterval(() => {
      fetchTasks();
      fetchStats();
    }, 15000);

    return () => clearInterval(interval);
  }, [filters]);

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
    <div className="container mx-auto py-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <HardDrive className="h-8 w-8 text-primary" /> Monitor de Tarefas
          </h1>
          <p className="text-muted-foreground mt-1">
            Monitoramento granular de execuções assíncronas (Celery)
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => confirmReprocess('events')}
            disabled={reprocessing}
          >
            <Zap className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} />
            Reprocessar Eventos
          </Button>
          <Button
            variant="outline"
            onClick={() => confirmReprocess('fila')}
            disabled={reprocessing}
          >
            <AlertTriangle className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} />
            Reprocessar Fila
          </Button>
          <Button variant="outline" onClick={() => { fetchTasks(); fetchStats(); }}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
        <Card className="p-4 border-l-4 border-gray-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Total</p>
            <h3 className="text-2xl font-bold">{stats.total}</h3>
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-yellow-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Pendentes</p>
            <h3 className="text-2xl font-bold">{stats.pending}</h3>
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-blue-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Processando</p>
            <h3 className="text-2xl font-bold">{stats.processing}</h3>
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-green-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Concluídos</p>
            <h3 className="text-2xl font-bold">{stats.completed}</h3>
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-red-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Falharam</p>
            <h3 className="text-2xl font-bold">{stats.failed}</h3>
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-gray-400">
          <div className="flex flex-col">
            <p className="text-xs font-bold text-muted-foreground uppercase">Cancelados</p>
            <h3 className="text-2xl font-bold">{stats.cancelled}</h3>
          </div>
        </Card>
      </div>

      {/* Filters */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="flex-1">
              <label className="text-sm font-medium mb-1 block">Nome da Tarefa</label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Buscar por nome..."
                  className="pl-8"
                  value={filters.task_name}
                  onChange={(e) => setFilters({...filters, task_name: e.target.value})}
                />
              </div>
            </div>
            <div className="w-full md:w-48">
              <label className="text-sm font-medium mb-1 block">Status</label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={filters.status}
                onChange={(e) => setFilters({...filters, status: e.target.value})}
              >
                <option value="all">Todos</option>
                <option value="PENDING">Pendente</option>
                <option value="PROCESSING">Processando</option>
                <option value="COMPLETED">Concluído</option>
                <option value="FAILED">Falhou</option>
                <option value="CANCELLED">Cancelado</option>
              </select>
            </div>
            <div className="w-full md:w-48">
              <label className="text-sm font-medium mb-1 block">Tipo</label>
              <Input
                placeholder="Tipo da tarefa"
                value={filters.task_type}
                onChange={(e) => setFilters({...filters, task_type: e.target.value})}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tasks Table */}
      <Card>
        <CardHeader>
          <CardTitle>Execuções de Tarefas</CardTitle>
          <CardDescription>
            Lista de todas as execuções de tarefas assíncronas
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Nome</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Correlation ID</TableHead>
                  <TableHead>Retries</TableHead>
                  <TableHead>Início</TableHead>
                  <TableHead>Fim</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center py-10 text-muted-foreground italic">
                      {loading ? 'Carregando...' : 'Nenhuma tarefa encontrada.'}
                    </TableCell>
                  </TableRow>
                ) : (
                  tasks.map((task) => (
                    <TableRow key={task.id}>
                      <TableCell>{getStatusBadge(task.status)}</TableCell>
                      <TableCell>
                        <div className="font-medium text-sm">{task.task_name}</div>
                      </TableCell>
                      <TableCell>
                        {task.task_type && <Badge variant="outline" className="text-[10px]">{task.task_type}</Badge>}
                      </TableCell>
                      <TableCell>
                        {task.correlation_id && (
                          <code className="text-[10px] bg-muted px-1 rounded">{task.correlation_id.slice(0, 8)}...</code>
                        )}
                      </TableCell>
                      <TableCell>{task.retry_count || 0}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {task.started_at ? new Date(task.started_at).toLocaleString('pt-BR') : '-'}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {task.finished_at ? new Date(task.finished_at).toLocaleString('pt-BR') : '-'}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex gap-1 justify-end">
                          {task.status === 'FAILED' && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleRetry(task.id)}
                              title="Reenviar"
                            >
                              <PlayCircle className="h-4 w-4" />
                            </Button>
                          )}
                          {(task.status === 'PENDING' || task.status === 'PROCESSING') && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleCancel(task.id)}
                              title="Cancelar"
                            >
                              <XCircle className="h-4 w-4" />
                            </Button>
                          )}
                          {task.error_message && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => alert(task.error_message)}
                              title="Ver erro"
                            >
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
          </div>
        </CardContent>
      </Card>

      {/* Confirmation Dialog */}
      <AlertDialog open={confirmDialog.open} onOpenChange={(open) => setConfirmDialog({ ...confirmDialog, open })}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar Reprocessamento</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmDialog.message}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setConfirmDialog({ open: false, action: null, message: '' })}>
              Cancelar
            </AlertDialogCancel>
            <AlertDialogAction onClick={executeConfirmedAction} disabled={reprocessing}>
              {reprocessing ? 'Processando...' : 'Confirmar'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default TasksMonitorPage;
