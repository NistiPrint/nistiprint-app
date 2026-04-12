import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
    Activity,
    CheckCircle2,
    Clock,
    Database,
    Eye,
    FileText,
    PlayCircle,
    RefreshCw,
    Search,
    TrendingUp
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Página de Monitoramento de Estoque - Arquitetura Event Sourcing
 * 
 * Unifica visualização de:
 * 1. Eventos de Produção (eventos_producao_v2)
 * 2. Fila de Processamento (fila_processamento_estoque) - legado
 * 3. Consolidações de Estoque
 */
function MonitoramentoEstoquePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('eventos');
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);

  // Estados para Eventos
  const [eventos, setEventos] = useState([]);
  const [eventosFilters, setEventosFilters] = useState({ tipo: 'all', status: 'all' });

  // Estados para Fila (legado)
  const [filaEstoque, setFilaEstoque] = useState([]);

  // Stats
  const [stats, setStats] = useState({
    eventos_pendentes: 0,
    eventos_processados: 0,
    fila_pendentes: 0,
    erros_24h: 0
  });

  const fetchEventos = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/producao/eventos?limit=100');
      const data = await response.json();
      if (data.success) {
        setEventos(data.eventos || []);
        setStats(prev => ({
          ...prev,
          eventos_pendentes: data.eventos?.filter(e => e.processado === false).length || 0,
          eventos_processados: data.eventos?.filter(e => e.processado === true).length || 0
        }));
      }
    } catch (e) {
      console.error('Erro ao carregar eventos:', e);
      toast.error('Erro ao carregar eventos de produção');
    } finally {
      setLoading(false);
    }
  };

  const fetchFilaEstoque = async () => {
    try {
      const response = await fetch('/api/v2/demanda_producao/fila-estoque');
      const data = await response.json();
      if (data.success) {
        setFilaEstoque(data.queue || []);
        setStats(prev => ({
          ...prev,
          fila_pendentes: data.queue?.filter(q => q.status === 'PENDENTE').length || 0
        }));
      }
    } catch (e) {
      console.error('Erro ao carregar fila:', e);
    }
  };

  const handleProcessarFila = async () => {
    setProcessing(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/processar-fila-estoque?limit=50', {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        toast.success(`${data.processed_count} tarefas processadas!`);
        fetchFilaEstoque();
      }
    } catch (e) {
      toast.error('Erro no processamento: ' + e.message);
    } finally {
      setProcessing(false);
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
        fetchEventos();
        fetchFilaEstoque();
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
        fetchEventos();
        fetchFilaEstoque();
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

  useEffect(() => {
    fetchEventos();
    fetchFilaEstoque();

    // Auto-refresh a cada 15s
    const interval = setInterval(() => {
      fetchEventos();
      fetchFilaEstoque();
    }, 15000);

    return () => clearInterval(interval);
  }, [activeTab]);

  const getStatusBadge = (evento) => {
    // eventos_producao_v2 tem apenas: processado (boolean)
    if (evento.processado === true) {
      return <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="h-3 w-3 mr-1" /> Processado</Badge>;
    }
    return <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200"><Clock className="h-3 w-3 mr-1" /> Pendente</Badge>;
  };

  const getTipoEventoBadge = (tipo) => {
    const badges = {
      'SINAL': <Badge variant="secondary" className="text-[10px]">Sinal</Badge>,
      'LIQUIDACAO': <Badge variant="default" className="text-[10px] bg-purple-600">Liquidação</Badge>
    };
    return badges[tipo] || <Badge variant="outline">{tipo}</Badge>;
  };

  return (
    <div className="container mx-auto py-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Activity className="h-8 w-8 text-primary" /> Monitoramento de Estoque
          </h1>
          <p className="text-muted-foreground mt-1">
            Eventos de produção e processamento de estoque em tempo real.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handleReprocessEvents}
            disabled={reprocessing}
          >
            <Zap className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} />
            Reprocessar Eventos
          </Button>
          <Button
            variant="outline"
            onClick={handleReprocessFila}
            disabled={reprocessing}
          >
            <AlertTriangle className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-pulse' : ''}`} />
            Reprocessar Fila
          </Button>
          <Button variant="outline" onClick={() => { fetchEventos(); fetchFilaEstoque(); }}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
          {activeTab === 'fila' && (
            <Button
              onClick={handleProcessFila}
              disabled={processing || reprocessing}
              variant="default"
            >
              <PlayCircle className={`h-4 w-4 mr-2 ${processing ? 'animate-pulse' : ''}`} />
              {processing ? 'Processando...' : 'Processar Fila'}
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="p-4 border-l-4 border-yellow-400">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-bold text-muted-foreground uppercase">Eventos Pendentes</p>
              <h3 className="text-2xl font-bold">{stats.eventos_pendentes}</h3>
            </div>
            <Clock className="h-8 w-8 text-yellow-400 opacity-50" />
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-green-400">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-bold text-muted-foreground uppercase">Eventos Processados</p>
              <h3 className="text-2xl font-bold">{stats.eventos_processados}</h3>
            </div>
            <CheckCircle2 className="h-8 w-8 text-green-400 opacity-50" />
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-blue-400">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-bold text-muted-foreground uppercase">Fila (Legado)</p>
              <h3 className="text-2xl font-bold">{stats.fila_pendentes}</h3>
            </div>
            <Database className="h-8 w-8 text-blue-400 opacity-50" />
          </div>
        </Card>
        <Card className="p-4 border-l-4 border-purple-400">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-xs font-bold text-muted-foreground uppercase">Última Atualização</p>
              <h3 className="text-sm font-bold">{new Date().toLocaleTimeString('pt-BR')}</h3>
            </div>
            <TrendingUp className="h-8 w-8 text-purple-400 opacity-50" />
          </div>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="eventos" value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2 mb-6">
          <TabsTrigger value="eventos" className="flex items-center gap-2">
            <FileText className="h-4 w-4" /> Eventos de Produção
          </TabsTrigger>
          <TabsTrigger value="fila" className="flex items-center gap-2">
            <Database className="h-4 w-4" /> Fila (Legado)
          </TabsTrigger>
        </TabsList>

        {/* Tab: Eventos de Produção */}
        <TabsContent value="eventos" className="space-y-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <div>
                <CardTitle>Eventos de Produção</CardTitle>
                <CardDescription>
                  Eventos imutáveis registrados no sistema Event Sourcing.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {/* Filtros */}
              <div className="flex gap-4 mb-4">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Buscar por item ou demanda..."
                    className="pl-8"
                    onChange={(e) => setEventosFilters({...eventosFilters, busca: e.target.value})}
                  />
                </div>
                <select
                  className="flex h-10 w-[150px] rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={eventosFilters.tipo}
                  onChange={(e) => setEventosFilters({...eventosFilters, tipo: e.target.value})}
                >
                  <option value="all">Todos Tipos</option>
                  <option value="SINAL">Sinal</option>
                  <option value="LIQUIDACAO">Liquidação</option>
                </select>
              </div>

              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Status</TableHead>
                      <TableHead>Tipo</TableHead>
                      <TableHead>Item</TableHead>
                      <TableHead>Estágio</TableHead>
                      <TableHead className="text-right">Quantidade</TableHead>
                      <TableHead>Data/Hora</TableHead>
                      <TableHead className="text-right">Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {eventos.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={7} className="text-center py-10 text-muted-foreground italic">
                          Nenhum evento registrado.
                        </TableCell>
                      </TableRow>
                    ) : (
                      eventos
                        .filter(e => eventosFilters.tipo === 'all' || e.tipo_evento === eventosFilters.tipo)
                        .filter(e => !eventosFilters.busca || 
                          String(e.item_demanda_id).includes(eventosFilters.busca) ||
                          String(e.demanda_id).includes(eventosFilters.busca))
                        .map((evento) => (
                        <TableRow key={evento.id}>
                          <TableCell>{getStatusBadge(evento)}</TableCell>
                          <TableCell>{getTipoEventoBadge(evento.tipo_evento)}</TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="font-medium text-sm">Item #{evento.item_demanda_id}</span>
                              <span className="text-[10px] text-muted-foreground">Demanda #{evento.demanda_id}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px] font-mono">
                              {evento.estagio}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right font-bold">
                            {parseFloat(evento.quantidade_reportada || 0).toLocaleString('pt-BR')}
                          </TableCell>
                          <TableCell className="text-[10px] text-muted-foreground">
                            {new Date(evento.created_at).toLocaleString('pt-BR')}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button 
                              size="sm" 
                              variant="ghost"
                              onClick={() => navigate(`/producao/demanda/${evento.demanda_id}`)}
                            >
                              <Eye className="h-3 w-3" />
                            </Button>
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

        {/* Tab: Fila de Estoque (Legado) */}
        <TabsContent value="fila" className="space-y-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <div>
                <CardTitle>Fila de Processamento (Legado)</CardTitle>
                <CardDescription>
                  Tarefas de processamento de estoque do sistema legado.
                </CardDescription>
              </div>
              <Button 
                onClick={handleProcessarFila} 
                disabled={processing || filaEstoque.filter(q => q.status === 'PENDENTE').length === 0}
              >
                {processing ? <RefreshCw className="h-4 w-4 mr-2 animate-spin" /> : <PlayCircle className="h-4 w-4 mr-2" />}
                Processar Fila
              </Button>
            </CardHeader>
            <CardContent>
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
                    {filaEstoque.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-10 text-muted-foreground italic">
                          Fila vazia.
                        </TableCell>
                      </TableRow>
                    ) : (
                      filaEstoque.map((task) => (
                        <TableRow key={task.id}>
                          <TableCell>{getStatusBadge(task.status, task.status === 'CONCLUIDO')}</TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="font-medium">{task.item?.sku || 'N/A'}</span>
                              <span className="text-[10px] text-muted-foreground">ID: {task.item_id}</span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px] font-mono">{task.tipo_operacao}</Badge>
                          </TableCell>
                          <TableCell className="text-right font-bold">
                            {parseFloat(task.quantidade || 0).toLocaleString('pt-BR')}
                          </TableCell>
                          <TableCell className="text-center text-xs">
                            {task.tentativas || 0} / 5
                          </TableCell>
                          <TableCell className="text-[10px] text-muted-foreground">
                            {new Date(task.created_at).toLocaleString('pt-BR')}
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

      {/* Info Box */}
      <Card className="mt-6 bg-blue-50 border-blue-200">
        <CardContent className="py-4">
          <div className="flex items-start gap-3">
            <Activity className="h-5 w-5 text-blue-600 mt-0.5" />
            <div className="text-sm text-blue-800">
              <p className="font-bold mb-1">Como funciona o processamento?</p>
              <ul className="list-disc list-inside space-y-1 text-blue-700">
                <li><strong>Eventos SINAL:</strong> Registrados quando etapas intermediárias são atualizadas (E1-E6)</li>
                <li><strong>Eventos LIQUIDACAO:</strong> Disparam reconciliação completa do estoque (E7 - Finalização)</li>
                <li><strong>Processamento:</strong> Ocorre automaticamente a cada 10 segundos via Celery</li>
                <li><strong>Fila Legado:</strong> Será descontinuada gradualmente</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default MonitoramentoEstoquePage;
