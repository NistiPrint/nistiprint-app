import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { 
  RefreshCw, 
  Clock, 
  CheckCircle2, 
  AlertCircle, 
  PlayCircle, 
  Trash2,
  Database,
  ArrowRight
} from 'lucide-react';
import { toast } from 'sonner';

function FilaEstoquePage() {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/fila-estoque');
      const data = await response.json();
      if (data.success) {
        setQueue(data.queue || []);
      }
    } catch (e) {
      toast.error('Erro ao carregar fila: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
    // Auto-refresh a cada 30 segundos se houver pendentes
    const interval = setInterval(() => {
      fetchQueue();
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleProcess = async () => {
    setProcessing(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/processar-fila-estoque?limit=50', {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        if (data.processed_count > 0) {
          toast.success(`${data.processed_count} tarefas processadas!`);
          fetchQueue();
        } else {
          toast.info('Nenhuma tarefa pendente processada.');
        }
      }
    } catch (e) {
      toast.error('Erro no processamento: ' + e.message);
    } finally {
      setProcessing(false);
    }
  };

  const handleRetry = async (taskId) => {
    try {
      const response = await fetch(`/api/v2/demanda_producao/retry-fila-estoque/${taskId}`, {
        method: 'POST'
      });
      const data = await response.json();
      
      if (data.success) {
        toast.success('Tarefa reiniciada! Será processada em instantes.');
        fetchQueue();
      } else {
        throw new Error(data.message || 'Erro ao reiniciar tarefa');
      }
    } catch (e) {
      toast.error('Erro ao reiniciar tarefa: ' + e.message);
    }
  };

  const getStatusBadge = (task) => {
    switch (task.status) {
      case 'PENDENTE': return <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200"><Clock className="h-3 w-3 mr-1" /> Pendente</Badge>;
      case 'PROCESSANDO': return <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200"><RefreshCw className="h-3 w-3 mr-1 animate-spin" /> Processando</Badge>;
      case 'CONCLUIDO': return <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="h-3 w-3 mr-1" /> Concluído</Badge>;
      case 'ERRO': 
        const isWaiting = task.proxima_execucao_at && new Date(task.proxima_execucao_at) > new Date();
        return (
          <Badge variant="destructive" className={isWaiting ? "bg-orange-500 hover:bg-orange-600" : ""}>
            <AlertCircle className="h-3 w-3 mr-1" /> 
            {isWaiting ? 'Aguardando Retentativa' : 'Erro Fatal'}
          </Badge>
        );
      default: return <Badge variant="secondary">{task.status}</Badge>;
    }
  };

  return (
    <div className="container mx-auto py-8">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Database className="h-8 w-8 text-primary" /> Fila de Processamento de Estoque
          </h1>
          <p className="text-muted-foreground mt-1">
            Gestão resiliente (Option A) de baixas de componentes e integridade de estoque.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={fetchQueue} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
          <Button onClick={handleProcess} disabled={processing || queue.filter(q => q.status === 'PENDENTE').length === 0}>
            {processing ? <RefreshCw className="h-4 w-4 mr-2 animate-spin" /> : <PlayCircle className="h-4 w-4 mr-2" />}
            Forçar Ciclo Manual
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <Card className="bg-yellow-50/50 border-yellow-100 p-4 text-center">
            <span className="text-3xl font-black text-yellow-700">{queue.filter(q => q.status === 'PENDENTE').length}</span>
            <p className="text-[10px] font-bold text-yellow-600 uppercase mt-1">Pendentes</p>
        </Card>
        <Card className="bg-blue-50/50 border-blue-100 p-4 text-center">
            <span className="text-3xl font-black text-blue-700">{queue.filter(q => q.status === 'PROCESSANDO').length}</span>
            <p className="text-[10px] font-bold text-blue-600 uppercase mt-1">Em Execução</p>
        </Card>
        <Card className="bg-green-50/50 border-green-100 p-4 text-center">
            <span className="text-3xl font-black text-green-700">{queue.filter(q => q.status === 'CONCLUIDO').length}</span>
            <p className="text-[10px] font-bold text-green-600 uppercase mt-1">Sucesso</p>
        </Card>
        <Card className="bg-red-50/50 border-red-100 p-4 text-center">
            <span className="text-3xl font-black text-red-700">{queue.filter(q => q.status === 'ERRO').length}</span>
            <p className="text-[10px] font-bold text-red-600 uppercase mt-1">Falhas / Retentativas</p>
        </Card>
      </div>

      <Card className="shadow-lg border-2">
        <CardHeader className="bg-muted/50 border-b py-4">
          <CardTitle className="text-lg">Fluxo Atômico de Baixas</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {queue.length === 0 ? (
            <div className="text-center py-20 text-muted-foreground italic">
              A fila está vazia no momento.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/20">
                    <TableHead className="font-bold">Status</TableHead>
                    <TableHead className="font-bold">Item / SKU</TableHead>
                    <TableHead className="font-bold">Ação</TableHead>
                    <TableHead className="text-right font-bold">Qtd</TableHead>
                    <TableHead className="text-center font-bold">Tentativas</TableHead>
                    <TableHead className="font-bold">Agendamento</TableHead>
                    <TableHead className="text-right font-bold">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {queue.map((task) => (
                    <React.Fragment key={task.id}>
                      <TableRow className="hover:bg-muted/5">
                        <TableCell>{getStatusBadge(task)}</TableCell>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium text-sm">{task.item?.sku || '-'}</span>
                            <span className="text-[10px] text-muted-foreground">Demanda: {task.demanda_id}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary" className="text-[10px] font-mono">
                            {task.campo}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-black">
                          {parseFloat(task.quantidade).toLocaleString('pt-BR')}
                        </TableCell>
                        <TableCell className="text-center">
                          <span className={`text-xs font-bold ${task.tentativas > 1 ? 'text-orange-600' : ''}`}>
                            {task.tentativas} / 5
                          </span>
                        </TableCell>
                        <TableCell className="text-[10px] text-muted-foreground">
                          {task.status === 'ERRO' && task.proxima_execucao_at ? (
                            <div className="flex flex-col">
                              <span className="font-bold text-orange-600 italic">Próxima tentativa:</span>
                              {new Date(task.proxima_execucao_at).toLocaleString('pt-BR')}
                            </div>
                          ) : (
                            new Date(task.created_at).toLocaleString('pt-BR')
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {task.status === 'ERRO' && (
                            <Button size="sm" variant="ghost" className="h-8 text-blue-600" onClick={() => handleRetry(task.id)}>
                              <RefreshCw className="h-3 w-3 mr-1" /> Reiniciar
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                      {task.status === 'ERRO' && task.mensagem_erro && (
                        <TableRow className="bg-red-50/30">
                          <TableCell colSpan={7} className="py-2 pl-10">
                            <div className="flex items-start gap-2 text-[11px] text-red-600 font-mono">
                              <AlertCircle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                              <span className="break-all">{task.mensagem_erro}</span>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default FilaEstoquePage;
