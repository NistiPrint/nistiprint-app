import { useLayout } from '@/contexts/LayoutContext';
import { cn } from '@/lib/utils';
import { Brain, Settings, Play, FileText } from 'lucide-react';
import { useEffect, useState, useRef } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Loader2, Save, TestTube2, CheckCircle2, AlertCircle, Terminal, ChevronDown, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { personalizadosService } from '@/services/personalizadosService';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

const aiMenu = [
  {
    name: 'Personalizados',
    href: '/ferramentas/ia',
    icon: Brain,
    description: 'Processamento de IA para personalizações'
  },
];

const MODEL_OPTIONS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash (recomendado)' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro (mais preciso)' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash (mais rápido)' },
];

const DEFAULT_PROMPT = `**Role**: You are a highly specialized AI assistant for an e-commerce operation. Your primary function is to act as a data extractor and processor for customer orders, with an extreme focus on accuracy.

**Context**: We sell customized planners on Shopee. After placing an order, customers use the Shopee chat to specify the name and, occasionally, an initial they want to be printed on the planner(s) they purchased. Your task is to analyze the complete order data, the list of items purchased, and the full chat conversation to accurately extract these personalization details.

**Objective**: For a given order, identify how many customizable items there are and extract the corresponding name and/or initial for each item from the chat messages. You must extract the name with strict adherence to the customer's original spelling and determine their final decision, even if they change their mind. The final output must be a clean JSON object for our production system.`;

const STATUS_CONFIG = {
  success: { label: 'Sucesso', icon: CheckCircle2, color: 'bg-green-100 text-green-800 border-green-300' },
  error: { label: 'Erro', icon: AlertCircle, color: 'bg-red-100 text-red-800 border-red-300' },
  db_error: { label: 'Erro DB', icon: AlertCircle, color: 'bg-orange-100 text-orange-800 border-orange-300' },
  no_response: { label: 'Sem Resposta', icon: AlertCircle, color: 'bg-yellow-100 text-yellow-800 border-yellow-300' },
};

function IAPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setLeftSidebarContent, setLeftSidebarMenuItems } = useLayout();

  // Config state
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [testingConfig, setTestingConfig] = useState(false);
  const [promptTemplate, setPromptTemplate] = useState('');
  const [modelName, setModelName] = useState('gemini-2.5-flash');
  const [maxProcessing, setMaxProcessing] = useState(50);
  const [testResult, setTestResult] = useState(null);

  // Processing state
  const [aiLimit, setAiLimit] = useState('');
  const [aiOrderSn, setAiOrderSn] = useState('');
  const [processingLogs, setProcessingLogs] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingComplete, setProcessingComplete] = useState(null);
  const logsEndRef = useRef(null);
  const pollRef = useRef(null);

  // Logs state
  const [logsIA, setLogsIA] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logFilterSn, setLogFilterSn] = useState('');
  const [expandedLogs, setExpandedLogs] = useState(new Set());
  const [page, setPage] = useState(1);
  const limit = 50;
  const [total, setTotal] = useState(0);

  // Auto-scroll do terminal
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [processingLogs]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, []);

  useEffect(() => {
    loadConfig();
    loadLogs();
  }, [page]);

  useEffect(() => {
    const sidebarContent = (
      <div className="flex flex-col gap-4">
        <div className="px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            IA
          </h2>
        </div>
        <nav className="space-y-1">
          <ul className="space-y-1">
            {aiMenu.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname.startsWith(item.href);
              return (
                <li key={item.name}>
                  <button
                    onClick={() => navigate(item.href)}
                    className={cn(
                      "w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all hover:bg-muted",
                      isActive && "bg-muted text-primary font-medium"
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <div>
                      <div className="leading-tight">{item.name}</div>
                      <div className="text-[10px] text-muted-foreground leading-tight">{item.description}</div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    );

    setLeftSidebarContent(sidebarContent);
    setLeftSidebarMenuItems(aiMenu);

    return () => {
      if (!window.location.pathname.startsWith('/ferramentas/ia')) {
        setLeftSidebarContent(null);
        setLeftSidebarMenuItems([]);
      }
    };
  }, [location.pathname, navigate]);

  const loadConfig = async () => {
    setLoadingConfig(true);
    try {
      const data = await personalizadosService.getConfig();
      if (data.success && data.data?.config) {
        const cfg = data.data.config;
        if (cfg.prompt_template) {
          setPromptTemplate(typeof cfg.prompt_template === 'string' ? cfg.prompt_template : cfg.prompt_template.text || DEFAULT_PROMPT);
        } else {
          setPromptTemplate(DEFAULT_PROMPT);
        }
        if (cfg.model_name) setModelName(cfg.model_name.replace(/"/g, ''));
        if (cfg.max_processing) setMaxProcessing(cfg.max_processing);
      } else {
        setPromptTemplate(DEFAULT_PROMPT);
      }
    } catch (e) {
      toast.error('Erro ao carregar configurações');
      setPromptTemplate(DEFAULT_PROMPT);
    } finally {
      setLoadingConfig(false);
    }
  };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    setTestResult(null);
    try {
      const data = await personalizadosService.updateConfig({
        prompt_template: promptTemplate,
        model_name: modelName,
        max_processing: maxProcessing,
      });
      if (data.success) {
        toast.success('Configurações salvas com sucesso!');
        setTestResult({ type: 'success', message: 'Configurações aplicadas' });
      } else {
        toast.error(data.message || 'Erro ao salvar');
      }
    } catch (e) {
      toast.error('Erro ao salvar configurações');
    } finally {
      setSavingConfig(false);
    }
  };

  const handleTestConfig = async () => {
    setTestingConfig(true);
    setTestResult(null);
    try {
      const data = await personalizadosService.processar({ limit: 1 });
      if (data.success) {
        setTestResult({
          type: 'success',
          message: data.data?.message || 'Teste executado com sucesso',
          detail: data.data?.result ? JSON.stringify(data.data.result, null, 2) : null,
        });
        toast.success('Teste concluído!');
      } else {
        setTestResult({ type: 'error', message: data.message || 'Erro no teste' });
        toast.error('Erro no teste');
      }
    } catch (e) {
      setTestResult({ type: 'error', message: `Erro: ${e.message}` });
      toast.error('Erro ao executar teste');
    } finally {
      setTestingConfig(false);
    }
  };

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString('pt-BR');
    setProcessingLogs(prev => [...prev, { timestamp, message, type }]);
  };

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const handleProcessAINames = async (e) => {
    e.preventDefault();

    setProcessingLogs([]);
    setProcessingComplete(null);
    stopPolling();
    setIsProcessing(true);
    addLog('Iniciando processamento de IA...', 'info');
    addLog(`Parâmetros: limit=${aiLimit === '0' ? 'todos' : (aiLimit || 'todos')}, order_sn=${aiOrderSn || 'todos'}`, 'info');

    const orderSn = aiOrderSn || null;
    const lastKnownLogIds = new Set();

    try {
      const data = await personalizadosService.processar({
        order_sn: orderSn || undefined,
        limit: aiLimit ? parseInt(aiLimit) : 0,
      });

      addLog(`Resposta da API: ${data.success ? 'OK' : 'ERRO'} - ${data.message || ''}`,
             data.success ? 'success' : 'error');

      if (data.task_id) {
        addLog(`Task ID: ${data.task_id} (background Celery)`, 'info');
      } else {
        addLog('Processamento síncrono — logs aparecerão conforme concluídos', 'info');
      }

      let pollCount = 0;
      let processingDone = false;
      const maxPolls = 200;

      pollRef.current = setInterval(async () => {
        pollCount++;
        if (processingDone) return;

        try {
          const params = { limit: 50 };
          if (orderSn) params.order_sn = orderSn;
          const logData = await personalizadosService.getAllLogs(params);

          if (logData.success && logData.data.logs) {
            for (const log of logData.data.logs) {
              if (!lastKnownLogIds.has(log.id)) {
                lastKnownLogIds.add(log.id);
                const statusLabel = log.status ? log.status.toUpperCase() : 'UNKNOWN';
                const color = log.status === 'error' ? 'error' : log.status === 'success' ? 'success' : 'info';
                addLog(`[${statusLabel}] ${log.order_sn} — ${log.executed_at ? new Date(log.executed_at).toLocaleTimeString('pt-BR') : ''}`, color);
                if (log.error_message) {
                  addLog(`  Erro: ${log.error_message}`, 'error');
                }
              }
            }

            if (logData.data.logs.length > 0 && pollCount > 3) {
              const latest = logData.data.logs[0];
              const age = Date.now() - new Date(latest.executed_at).getTime();
              if (age > 20000) {
                processingDone = true;
                stopPolling();
                setIsProcessing(false);
                setProcessingComplete({ success: true, message: `Processamento concluído. ${logData.data.total || logData.data.logs.length} log(s) encontrado(s).` });
                addLog('✓ Processamento concluído!', 'success');
                loadLogs();
              }
            }
          }
        } catch (err) {
        }

        if (pollCount >= maxPolls) {
          processingDone = true;
          stopPolling();
          setIsProcessing(false);
          setProcessingComplete({ success: true, message: 'Timeout: processamento pode ainda estar em andamento.' });
          addLog('⏱ Timeout após 10 minutos. Verifique os logs.', 'warning');
        }
      }, 3000);

    } catch (error) {
      addLog(`Erro: ${error.message}`, 'error');
      stopPolling();
      setIsProcessing(false);
      setProcessingComplete({ success: false, message: error.message });
    }
  };

  const loadLogs = async () => {
    setLoadingLogs(true);
    try {
      const params = { limit, offset: (page - 1) * limit };
      if (logFilterSn) params.order_sn = logFilterSn;
      const data = await personalizadosService.getAllLogs(params);
      if (data.success) {
        setLogsIA(data.data.logs || []);
        setTotal(data.data.total || 0);
      } else {
        toast.error('Erro ao carregar logs');
      }
    } catch (err) {
      toast.error(`Erro: ${err.message}`);
    } finally {
      setLoadingLogs(false);
    }
  };

  const handleSearchLogs = () => {
    setPage(1);
    loadLogs();
  };

  const toggleLogExpand = (logId) => {
    setExpandedLogs(prev => {
      const next = new Set(prev);
      if (next.has(logId)) next.delete(logId);
      else next.add(logId);
      return next;
    });
  };

  const CollapsibleSection = ({ icon: Icon, title, content, defaultOpen = false }) => {
    const [open, setOpen] = useState(defaultOpen);

    return (
      <div className="border rounded overflow-hidden">
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <Icon className="h-4 w-4 text-muted-foreground" />
          {title}
        </button>
        {open && content && (
          <pre className="text-xs bg-white p-3 overflow-x-auto max-h-96 whitespace-pre-wrap border-t">
            {typeof content === 'string' ? content : JSON.stringify(content, null, 2)}
          </pre>
        )}
      </div>
    );
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold">IA - Inteligência Artificial</h1>
        <p className="text-muted-foreground mt-1">Gerenciamento de processamento de IA para personalizações</p>
      </div>

      <Tabs defaultValue="config" className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="config">
            <Settings className="w-4 h-4 mr-2" /> Configurações
          </TabsTrigger>
          <TabsTrigger value="batch">
            <Play className="w-4 h-4 mr-2" /> Processamento em Lote
          </TabsTrigger>
          <TabsTrigger value="individual">
            <Play className="w-4 h-4 mr-2" /> Processamento Individual
          </TabsTrigger>
          <TabsTrigger value="logs">
            <FileText className="w-4 h-4 mr-2" /> Logs de Execução
          </TabsTrigger>
        </TabsList>

        <TabsContent value="config" className="mt-6">
          {loadingConfig ? (
            <div className="flex justify-center items-center h-64">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-6 max-w-4xl">
              <Card>
                <CardHeader>
                  <CardTitle>Prompt Template</CardTitle>
                  <CardDescription>
                    Instruções que a IA recebe para extrair nomes de personalização. Use Title Case e preserve ortografia original.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Textarea
                    value={promptTemplate}
                    onChange={(e) => setPromptTemplate(e.target.value)}
                    className="min-h-[300px] font-mono text-sm"
                    placeholder="Cole aqui o prompt template..."
                  />
                  <p className="text-xs text-muted-foreground mt-2">
                    Dica: Use variáveis como {'{order_id}'}, {'{items}'}, {'{chat_messages}'} se o service as substitui dinamicamente.
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Modelo e Processamento</CardTitle>
                  <CardDescription>Configure qual modelo Gemini usar e quantos pedidos processar por vez.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="model-name">Modelo Gemini</Label>
                      <Select value={modelName} onValueChange={setModelName}>
                        <SelectTrigger id="model-name">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {MODEL_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="max-processing">Limite de Pedidos</Label>
                      <Input
                        id="max-processing"
                        type="number"
                        min={1}
                        max={500}
                        value={maxProcessing}
                        onChange={(e) => setMaxProcessing(parseInt(e.target.value) || 50)}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>

              {testResult && (
                <Card className={testResult.type === 'success' ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'}>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      {testResult.type === 'success' ? (
                        <CheckCircle2 className="h-5 w-5 text-green-600" />
                      ) : (
                        <AlertCircle className="h-5 w-5 text-red-600" />
                      )}
                      {testResult.type === 'success' ? 'Sucesso' : 'Erro'}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm">{testResult.message}</p>
                    {testResult.detail && (
                      <pre className="mt-2 bg-white/50 p-3 rounded text-xs overflow-x-auto">
                        <code>{testResult.detail}</code>
                      </pre>
                    )}
                  </CardContent>
                </Card>
              )}

              <div className="flex gap-3 justify-end">
                <Button
                  variant="outline"
                  onClick={handleTestConfig}
                  disabled={testingConfig}
                >
                  {testingConfig ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <TestTube2 className="mr-2 h-4 w-4" />
                  )}
                  Testar Prompt
                </Button>
                <Button
                  onClick={handleSaveConfig}
                  disabled={savingConfig}
                >
                  {savingConfig ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="mr-2 h-4 w-4" />
                  )}
                  Salvar Configurações
                </Button>
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="batch" className="mt-6">
          <div className="space-y-4 max-w-4xl">
            <Card>
              <CardHeader>
                <CardTitle>Processamento em Lote</CardTitle>
                <CardDescription>
                  Processe múltiplos pedidos para identificar nomes para personalização utilizando IA.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleProcessAINames} className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="ai-limit">Limite de Pedidos</Label>
                      <Input
                        id="ai-limit"
                        placeholder="Deixe vazio para todos"
                        value={aiLimit}
                        onChange={(e) => setAiLimit(e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">0 ou vazio = processar todos os pedidos pendentes</p>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="ai-order-sn">Pedido Específico (opcional)</Label>
                      <Input
                        id="ai-order-sn"
                        placeholder="Ex: 260101ABCDEF"
                        value={aiOrderSn}
                        onChange={(e) => setAiOrderSn(e.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">Preencha para processar apenas um pedido</p>
                    </div>
                  </div>
                  <Button type="submit" disabled={isProcessing} className="w-full">
                    {isProcessing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    {isProcessing ? 'Processando...' : 'Iniciar Processamento em Lote'}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {processingLogs.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Log de Execução</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="bg-black text-green-400 p-4 rounded-lg font-mono text-sm h-64 overflow-y-auto">
                    {processingLogs.map((log, idx) => (
                      <div key={idx} className={cn(
                        "mb-1",
                        log.type === 'error' && "text-red-400",
                        log.type === 'success' && "text-green-300",
                        log.type === 'warning' && "text-yellow-400"
                      )}>
                    [{log.timestamp}] {log.message}
                  </div>
                ))}
                  <div ref={logsEndRef} />
                </div>
              </CardContent>
            </Card>
            )}

            {processingComplete && (
              <Card className={processingComplete.success ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'}>
                <CardContent className="pt-6">
                  <p className="font-medium">{processingComplete.message}</p>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        <TabsContent value="individual" className="mt-6">
          <div className="space-y-4 max-w-4xl">
            <Card>
              <CardHeader>
                <CardTitle>Processamento Individual</CardTitle>
                <CardDescription>
                  Processe um pedido específico informando o order_sn.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleProcessAINames} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="individual-order-sn">Order SN do Pedido</Label>
                    <Input
                      id="individual-order-sn"
                      placeholder="Ex: 260101ABCDEF"
                      value={aiOrderSn}
                      onChange={(e) => setAiOrderSn(e.target.value)}
                      required
                    />
                  </div>
                  <Button type="submit" disabled={isProcessing} className="w-full">
                    {isProcessing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-4 w-4" />
                    )}
                    {isProcessing ? 'Processando...' : 'Processar Pedido'}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {processingLogs.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Log de Execução</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="bg-black text-green-400 p-4 rounded-lg font-mono text-sm h-64 overflow-y-auto">
                    {processingLogs.map((log, idx) => (
                      <div key={idx} className={cn(
                        "mb-1",
                        log.type === 'error' && "text-red-400",
                        log.type === 'success' && "text-green-300",
                        log.type === 'warning' && "text-yellow-400"
                      )}>
                    [{log.timestamp}] {log.message}
                  </div>
                ))}
                  <div ref={logsEndRef} />
                </div>
              </CardContent>
            </Card>
            )}
          </div>
        </TabsContent>

        <TabsContent value="logs" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Logs de Execução IA</CardTitle>
              <CardDescription>Histórico de processamentos de IA</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="p-4 border-b">
                <div className="flex gap-3 items-end">
                  <div className="flex-1">
                    <Label className="text-sm font-medium mb-1 block">Pedido (order_sn)</Label>
                    <Input
                      value={logFilterSn}
                      onChange={(e) => setLogFilterSn(e.target.value)}
                      placeholder="Ex: 260101ABCDEF"
                      onKeyDown={(e) => e.key === 'Enter' && handleSearchLogs()}
                    />
                  </div>
                  <Button onClick={handleSearchLogs} disabled={loadingLogs}>
                    <Search className="h-4 w-4 mr-2" /> Buscar
                  </Button>
                  <Button variant="outline" onClick={() => { setPage(1); loadLogs(); }}>
                    <RefreshCw className="h-4 w-4 mr-2" /> Atualizar
                  </Button>
                </div>
              </div>

              {loadingLogs ? (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : logsIA.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  Nenhum log encontrado
                </div>
              ) : (
                <div className="divide-y">
                  {logsIA.map((log) => {
                    const statusCfg = STATUS_CONFIG[log.status] || { label: log.status, icon: AlertCircle, color: 'bg-gray-100 text-gray-800 border-gray-300' };
                    const StatusIcon = statusCfg.icon;
                    const isExpanded = expandedLogs.has(log.id);

                    return (
                      <div key={log.id} className="hover:bg-gray-50/50 transition-colors">
                        <div
                          className="flex items-center gap-4 px-4 py-3 cursor-pointer"
                          onClick={() => toggleLogExpand(log.id)}
                        >
                          <button className="text-muted-foreground hover:text-foreground">
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>

                          <Badge variant="outline" className={statusCfg.color}>
                            <StatusIcon className="h-3 w-3 mr-1" />
                            {statusCfg.label}
                          </Badge>

                          <code className="text-sm font-mono bg-gray-100 px-2 py-0.5 rounded">
                            {log.order_sn}
                          </code>

                          <span className="text-sm text-muted-foreground ml-auto">
                            {log.executed_at ? format(new Date(log.executed_at), 'dd/MM/yyyy HH:mm:ss', { locale: ptBR }) : '-'}
                          </span>
                        </div>

                        {isExpanded && (
                          <div className="px-4 pb-4 space-y-3">
                            {log.error_message && (
                              <div className="bg-red-50 border border-red-200 rounded p-3">
                                <p className="text-sm font-medium text-red-800">Erro:</p>
                                <pre className="text-xs text-red-700 mt-1 whitespace-pre-wrap">{log.error_message}</pre>
                              </div>
                            )}

                            <CollapsibleSection
                              icon={Terminal}
                              title="Prompt enviado à IA"
                              content={log.input_data}
                              defaultOpen={false}
                            />

                            {log.model_result && (
                              <CollapsibleSection
                                icon={Brain}
                                title="Resposta da IA (JSON)"
                                content={log.model_result}
                                defaultOpen={false}
                              />
                            )}

                            {log.extracted_personalization && (
                              <CollapsibleSection
                                icon={FileText}
                                title="Personalizações extraídas"
                                content={log.extracted_personalization}
                                defaultOpen={false}
                              />
                            )}

                            {log.metadata && (
                              <CollapsibleSection
                                icon={Terminal}
                                title="Metadata"
                                content={log.metadata}
                                defaultOpen={false}
                              />
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-muted-foreground">
                Página {page} de {totalPages} ({total} total)
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage(p => p - 1)}
                >
                  Anterior
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(p => p + 1)}
                >
                  Próxima
                </Button>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default IAPage;
