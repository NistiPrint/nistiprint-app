import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
  RefreshCw, 
  Clock, 
  CheckCircle2, 
  AlertCircle, 
  PlayCircle, 
  Database,
  History,
  Activity,
  Search,
  Filter,
  ArrowUpDown,
  FileSpreadsheet
} from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';

function MonitoramentoPage() {
  const [activeTab, setActiveTab] = useState('estoque');
  const [loading, setLoading] = useState(false);
  const [overviewStats, setOverviewStats] = useState(null);

  // States para Fila de Estoque (Aba 1)
  const [stockQueue, setStockQueue] = useState([]);
  const [stockFilters, setStockFilters] = useState({ sku: '', operacao: 'all' });
  const [processingStock, setProcessingStock] = useState(false);

  // States para Consolidações (Aba 2)
  const [consolidations, setConsolidations] = useState([]);

  // States para Tarefas de Sistema (Aba 3)
  const [systemTasks, setSystemTasks] = useState([]);

  const fetchOverview = async () => {
    try {
      const response = await fetch('/api/v2/demanda_producao/monitoring/overview');
      const data = await response.json();
      if (data.success) {
        setOverviewStats(data.stats);
      }
    } catch (e) {
      console.error('Erro ao carregar overview:', e);
    }
  };

  const fetchStockQueue = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/fila-estoque');
      const data = await response.json();
      if (data.success) {
        setStockQueue(data.queue || []);
      }
    } catch (e) {
      toast.error('Erro ao carregar fila de estoque: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchConsolidations = async () => {
    setLoading(true);
    try {
      // Usaremos o endpoint existente de consolidacoes_pedido (pode precisar de um novo se for muito pesado)
      const response = await fetch('/api/v2/consolidar-base/historico');
      const data = await response.json();
      if (data.success) {
        setConsolidations(data.historico || []);
      }
    } catch (e) {
      toast.error('Erro ao carregar histórico de consolidações');
    } finally {
      setLoading(false);
    }
  };

  const fetchSystemTasks = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/monitoring/system-tasks?limit=50');
      const data = await response.json();
      if (data.success) {
        setSystemTasks(data.tasks || []);
      }
    } catch (e) {
      toast.error('Erro ao carregar tarefas de sistema');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
    if (activeTab === 'estoque') fetchStockQueue();
    if (activeTab === 'consolidacoes') fetchConsolidations();
    if (activeTab === 'sistema') fetchSystemTasks();
    
    const interval = setInterval(fetchOverview, 30000);
    return () => clearInterval(interval);
  }, [activeTab]);

  const handleProcessStock = async () => {
    setProcessingStock(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/processar-fila-estoque?limit=50', {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        toast.success(`${data.processed_count} tarefas processadas!`);
        fetchStockQueue();
        fetchOverview();
      }
    } catch (e) {
      toast.error('Erro no processamento: ' + e.message);
    } finally {
      setProcessingStock(false);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'PENDENTE':
      case 'PENDING':
        return <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200"><Clock className="h-3 w-3 mr-1" /> Pendente</Badge>;
      case 'PROCESSANDO':
      case 'PROCESSING':
        return <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200"><RefreshCw className="h-3 w-3 mr-1 animate-spin" /> Processando</Badge>;
      case 'CONCLUIDO':
      case 'COMPLETED':
      case 'PRONTO':
        return <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="h-3 w-3 mr-1" /> Concluído</Badge>;
      case 'ERRO':
      case 'FAILED':
        return <Badge variant="destructive"><AlertCircle className="h-3 w-3 mr-1" /> Erro</Badge>;
      default: return <Badge variant="secondary">{status}</Badge>;
    }
  };

  return (
    <div className="container mx-auto py-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Activity className="h-8 w-8 text-primary" /> Monitoramento de Atividades
          </h1>
          <p className="text-muted-foreground mt-1">
            Gestão centralizada de processos assíncronos e integridade do sistema.
          </p>
        </div>
        <div className="flex gap-2">
            <Button variant="outline" onClick={() => { fetchOverview(); if(activeTab === 'estoque') fetchStockQueue(); }}>
                <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar Tudo
            </Button>
        </div>
      </div>

      {/* Overview Stats */}
      {overviewStats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            <Card className="p-4 border-l-4 border-yellow-400">
                <div className="flex justify-between items-center">
                    <div>
                        <p className="text-xs font-bold text-muted-foreground uppercase">Fila de Estoque</p>
                        <h3 className="text-2xl font-bold">{overviewStats.stock.PENDENTE} pendentes</h3>
                    </div>
                    <Database className="h-8 w-8 text-yellow-400 opacity-50" />
                </div>
            </Card>
            <Card className="p-4 border-l-4 border-blue-400">
                <div className="flex justify-between items-center">
                    <div>
                        <p className="text-xs font-bold text-muted-foreground uppercase">Consolidações (24h)</p>
                        <h3 className="text-2xl font-bold">{overviewStats.consolidations.PRONTO} concluídas</h3>
                    </div>
                    <FileSpreadsheet className="h-8 w-8 text-blue-400 opacity-50" />
                </div>
            </Card>
            <Card className="p-4 border-l-4 border-green-400">
                <div className="flex justify-between items-center">
                    <div>
                        <p className="text-xs font-bold text-muted-foreground uppercase">Tarefas de Sistema</p>
                        <h3 className="text-2xl font-bold">{overviewStats.system_tasks.COMPLETED} sucessos</h3>
                    </div>
                    <Activity className="h-8 w-8 text-green-400 opacity-50" />
                </div>
            </Card>
        </div>
      )}

      <Tabs defaultValue="estoque" value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-3 mb-6">
          <TabsTrigger value="estoque" className="flex items-center gap-2">
            <Database className="h-4 w-4" /> Estoque
          </TabsTrigger>
          <TabsTrigger value="consolidacoes" className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4" /> Consolidações
          </TabsTrigger>
          <TabsTrigger value="sistema" className="flex items-center gap-2">
            <Activity className="h-4 w-4" /> Sistema
          </TabsTrigger>
        </TabsList>

        <TabsContent value="estoque" className="space-y-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <div>
                <CardTitle>Fila de Processamento de Estoque</CardTitle>
                <CardDescription>Movimentações de componentes aguardando processamento atômico.</CardDescription>
              </div>
              <Button onClick={handleProcessStock} disabled={processingStock || stockQueue.filter(q => q.status === 'PENDENTE').length === 0}>
                {processingStock ? <RefreshCw className="h-4 w-4 mr-2 animate-spin" /> : <PlayCircle className="h-4 w-4 mr-2" />}
                Forçar Processamento
              </Button>
            </CardHeader>
            <CardContent>
              {/* Filtros */}
              <div className="flex gap-4 mb-4">
                <div className="relative flex-1">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input 
                        placeholder="Filtrar por SKU..." 
                        className="pl-8" 
                        value={stockFilters.sku}
                        onChange={(e) => setStockFilters({...stockFilters, sku: e.target.value})}
                    />
                </div>
                <select 
                    className="flex h-10 w-[180px] rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={stockFilters.operacao}
                    onChange={(e) => setStockFilters({...stockFilters, operacao: e.target.value})}
                >
                    <option value="all">Todas Operações</option>
                    <option value="ETAPA">Etapas de Produção</option>
                    <option value="BOM">Processamento BOM</option>
                    <option value="ESTORNO">Estornos</option>
                </select>
              </div>

              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Status</TableHead>
                      <TableHead>Item / SKU</TableHead>
                      <TableHead>Operação</TableHead>
                      <TableHead className="text-right">Qtd</TableHead>
                      <TableHead className="text-center">Tentativas</TableHead>
                      <TableHead>Data</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stockQueue.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-10 text-muted-foreground italic">Nenhuma tarefa pendente.</TableCell>
                      </TableRow>
                    ) : (
                      stockQueue
                        .filter(task => !stockFilters.sku || task.item?.sku?.toLowerCase().includes(stockFilters.sku.toLowerCase()))
                        .filter(task => stockFilters.operacao === 'all' || task.tipo_operacao.includes(stockFilters.operacao))
                        .map((task) => (
                        <TableRow key={task.id}>
                          <TableCell>{getStatusBadge(task.status)}</TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="font-medium">{task.item?.sku || 'N/A'}</span>
                              <span className="text-[10px] text-muted-foreground">ID: {task.item_id}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px] font-mono">{task.tipo_operacao}</Badge>
                          </TableCell>
                          <TableCell className="text-right font-bold">{parseFloat(task.quantidade).toLocaleString('pt-BR')}</TableCell>
                          <TableCell className="text-center text-xs">{task.tentativas} / 5</TableCell>
                          <TableCell className="text-[10px] text-muted-foreground">{new Date(task.created_at).toLocaleString('pt-BR')}</TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="consolidacoes">
          <Card>
            <CardHeader>
              <CardTitle>Histórico de Consolidações</CardTitle>
              <CardDescription>Registro de processamento de planilhas de pedidos dos marketplaces.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Data</TableHead>
                      <TableHead>Plataforma</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Período</TableHead>
                      <TableHead className="text-right">Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {consolidations.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center py-10 text-muted-foreground italic">Nenhuma consolidação registrada.</TableCell>
                      </TableRow>
                    ) : (
                      consolidations.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell className="text-sm">{new Date(item.created_at).toLocaleString('pt-BR')}</TableCell>
                          <TableCell>{item.platform}</TableCell>
                          <TableCell>{getStatusBadge(item.status)}</TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {new Date(item.period_filter_start).toLocaleDateString()} - {new Date(item.period_filter_end).toLocaleDateString()}
                          </TableCell>
                          <TableCell className="text-right">
                             <Button size="sm" variant="ghost">Ver Detalhes</Button>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sistema">
          <Card>
            <CardHeader>
              <CardTitle>Tarefas de Sistema</CardTitle>
              <CardDescription>Monitoramento de sincronizações, renovação de tokens e tarefas de manutenção.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Data</TableHead>
                      <TableHead>Tarefa</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Duração</TableHead>
                      <TableHead>Info</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {systemTasks.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center py-10 text-muted-foreground italic">
                            Aguardando primeiras execuções após atualização do sistema.
                        </TableCell>
                      </TableRow>
                    ) : (
                      systemTasks.map((task) => (
                        <TableRow key={task.id}>
                          <TableCell className="text-sm">{new Date(task.created_at).toLocaleString('pt-BR')}</TableCell>
                          <TableCell className="font-medium">{task.task_name}</TableCell>
                          <TableCell>{getStatusBadge(task.status)}</TableCell>
                          <TableCell className="text-xs">
                              {task.finished_at && task.started_at ? 
                                `${Math.round((new Date(task.finished_at) - new Date(task.started_at)) / 1000)}s` : '-'}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                              {JSON.stringify(task.metadata)}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default MonitoramentoPage;
