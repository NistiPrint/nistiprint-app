import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { 
  Clock, 
  RefreshCw, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle,
  Settings,
  Info
} from 'lucide-react';

/**
 * Tarefas Agendadas Page
 * 
 * Interface administrativa para habilitar/desabilitar e configurar frequência
 * de tarefas periódicas do Celery Beat.
 */
function TarefasAgendadasPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [tasks, setTasks] = useState({});
  const [showReloadWarning, setShowReloadWarning] = useState(false);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/admin/task-schedules');
      const data = await response.json();
      
      if (data.success) {
        setTasks(data.data || {});
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

  const handleToggle = async (taskName, currentEnabled) => {
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
        if (data.warning) {
          setShowReloadWarning(true);
        }
        fetchTasks();
      } else {
        toast.error(data.error || 'Erro ao atualizar tarefa');
      }
    } catch (e) {
      console.error('Erro ao atualizar tarefa:', e);
      toast.error('Erro ao atualizar tarefa');
    } finally {
      setSaving(false);
    }
  };

  const handleFrequencyChange = async (taskName, newFrequency) => {
    setSaving(true);
    try {
      const response = await fetch(`/api/v2/admin/task-schedules/${taskName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schedule_seconds: parseInt(newFrequency) })
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success(data.message);
        if (data.warning) {
          setShowReloadWarning(true);
        }
        fetchTasks();
      } else {
        toast.error(data.error || 'Erro ao atualizar frequência');
      }
    } catch (e) {
      console.error('Erro ao atualizar frequência:', e);
      toast.error('Erro ao atualizar frequência');
    } finally {
      setSaving(false);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      const response = await fetch('/api/v2/admin/task-schedules/reload', {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success(data.message);
        setShowReloadWarning(false);
      } else {
        toast.error(data.error || 'Erro ao solicitar recarga');
      }
    } catch (e) {
      console.error('Erro ao solicitar recarga:', e);
      toast.error('Erro ao solicitar recarga');
    } finally {
      setReloading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const formatFrequency = (seconds) => {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}min`;
    return `${Math.floor(seconds / 3600)}h`;
  };

  const getTaskIcon = (taskName) => {
    if (taskName.includes('sync') || taskName.includes('token')) return <RefreshCw className="w-4 h-4" />;
    if (taskName.includes('fila') || taskName.includes('bling')) return <Clock className="w-4 h-4" />;
    if (taskName.includes('evento') || taskName.includes('producao')) return <Settings className="w-4 h-4" />;
    return <Clock className="w-4 h-4" />;
  };

  return (
    <div className="container mx-auto py-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Clock className="h-8 w-8 text-primary" /> Tarefas Agendadas
          </h1>
          <p className="text-muted-foreground mt-1">
            Configure tarefas periódicas do Celery Beat
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { fetchTasks(); }}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
          {showReloadWarning && (
            <Button onClick={handleReload} disabled={reloading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${reloading ? 'animate-spin' : ''}`} />
              Recarregar Worker
            </Button>
          )}
        </div>
      </div>

      {/* Warning Banner */}
      {showReloadWarning && (
        <Card className="mb-6 border-yellow-400 bg-yellow-50">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-yellow-600 mt-0.5" />
              <div className="flex-1">
                <p className="font-medium text-yellow-900">
                  Alterações de configuração requerem reinício do worker
                </p>
                <p className="text-sm text-yellow-700 mt-1">
                  As alterações de frequência só serão aplicadas após reiniciar o container do worker.
                </p>
              </div>
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => setShowReloadWarning(false)}
              >
                Entendi
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tasks List */}
      <div className="space-y-4">
        {loading ? (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              Carregando tarefas...
            </CardContent>
          </Card>
        ) : Object.keys(tasks).length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-muted-foreground">
              Nenhuma tarefa configurada
            </CardContent>
          </Card>
        ) : (
          Object.entries(tasks).map(([taskName, taskConfig]) => (
            <Card key={taskName}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {getTaskIcon(taskName)}
                      <CardTitle className="text-lg">{taskName}</CardTitle>
                      <Badge variant={taskConfig.enabled ? 'default' : 'secondary'}>
                        {taskConfig.enabled ? 'Ativa' : 'Inativa'}
                      </Badge>
                    </div>
                    <CardDescription>{taskConfig.description}</CardDescription>
                  </div>
                  <Switch
                    checked={taskConfig.enabled}
                    onCheckedChange={() => handleToggle(taskName, taskConfig.enabled)}
                    disabled={saving}
                  />
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <div className="flex-1">
                    <label className="text-sm font-medium mb-1 block">Frequência</label>
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min="1"
                        value={taskConfig.schedule_seconds}
                        onChange={(e) => handleFrequencyChange(taskName, e.target.value)}
                        disabled={saving || !taskConfig.enabled}
                        className="w-32"
                      />
                      <span className="text-sm text-muted-foreground">
                        ({formatFrequency(taskConfig.schedule_seconds)})
                      </span>
                    </div>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Info className="w-3 h-3" />
                      Task: {taskConfig.task_name}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Info Card */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Info className="h-4 w-4" /> Informações
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>• Tarefas desabilitadas não serão executadas pelo Celery Beat</p>
          <p>• Alterações de frequência requerem reinício do worker</p>
          <p>• O status de execução pode ser monitorado na página de Monitor de Tarefas</p>
        </CardContent>
      </Card>
    </div>
  );
}

export default TarefasAgendadasPage;
