import React, { useState, useRef, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Upload, Wand2, RefreshCw, Activity, FileText, Search, Terminal, Play, Square, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import QueueMonitor from '@/components/admin/QueueMonitor';
import { personalizadosService } from '@/services/personalizadosService';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

const STATUS_COLORS = {
  success: 'bg-green-100 text-green-800',
  error: 'bg-red-100 text-red-800',
  db_error: 'bg-orange-100 text-orange-800',
  no_response: 'bg-yellow-100 text-yellow-800',
};

function FerramentasPage() {
  const [loadingImport, setLoadingImport] = useState(false);
  const [loadingAI, setLoadingAI] = useState(false);
  const [numeroLoja, setNumeroLoja] = useState('');
  const [aiLimit, setAiLimit] = useState('');
  const [aiOrderSn, setAiOrderSn] = useState('');

  // Terminal-like output
  const [processingLogs, setProcessingLogs] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingComplete, setProcessingComplete] = useState(null);
  const logsEndRef = useRef(null);
  const pollRef = useRef(null);

  // Estado para logs de IA (histórico)
  const [logsIA, setLogsIA] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logFilterSn, setLogFilterSn] = useState('');
  const [expandedLogs, setExpandedLogs] = useState(new Set());

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

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString('pt-BR');
    setProcessingLogs(prev => [...prev, { timestamp, message, type }]);
  };

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const handleImportBlingOrder = async (e) => {
    e.preventDefault();
    if (!numeroLoja) {
      toast.warning('Número do pedido é obrigatório.');
      return;
    }

    setLoadingImport(true);
    try {
      const response = await fetch('/api/v2/ferramentas/importar_pedido_bling', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ numero_loja: numeroLoja }),
      });

      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
        setNumeroLoja('');
      } else {
        toast.error(data.message || 'Erro ao importar pedido.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingImport(false);
    }
  };

  const handleProcessAINames = async (e) => {
    e.preventDefault();

    // Reset terminal
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
        limit: aiLimit ? parseInt(aiLimit) : 0,  // 0 = todos
      });

      addLog(`Resposta da API: ${data.success ? 'OK' : 'ERRO'} - ${data.message || ''}`,
             data.success ? 'success' : 'error');

      if (data.task_id) {
        addLog(`Task ID: ${data.task_id} (background Celery)`, 'info');
      } else {
        addLog('Processamento síncrono — logs aparecerão conforme concluídos', 'info');
      }

      // Unified single polling: fetches logs, displays new ones, detects completion
      let pollCount = 0;
      let processingDone = false;
      const maxPolls = 200; // 10 minutes at 3s intervals

      pollRef.current = setInterval(async () => {
        pollCount++;
        if (processingDone) return;

        try {
          const params = { limit: 50 };
          if (orderSn) params.order_sn = orderSn;
          const logData = await personalizadosService.getAllLogs(params);

          if (logData.success && logData.data.logs) {
            // Display new logs
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

            // Detect completion: latest log is > 20s old
            if (logData.data.logs.length > 0 && pollCount > 3) {
              const latest = logData.data.logs[0];
              const age = Date.now() - new Date(latest.executed_at).getTime();
              if (age > 20000) {
                processingDone = true;
                stopPolling();
                setIsProcessing(false);
                setProcessingComplete({ success: true, message: `Processamento concluído. ${logData.data.total || logData.data.logs.length} log(s) encontrado(s).` });
                addLog('✓ Processamento concluído!', 'success');
                loadLogsIA(); // Refresh history tab
              }
            }
          }
        } catch (err) {
          // Silent — polling continues
        }

        // Timeout after 10 minutes
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

  const handleUpdateProductStatus = async () => {
      if (!confirm('Isso atualizará o status de TODOS os produtos para "ativo". Continuar?')) return;

      try {
          const response = await fetch('/api/v2/ferramentas/update_product_status', {
              headers: { 'Accept': 'application/json'}
          });
          const data = await response.json();
          if (data.success) {
              toast.success(data.message);
          } else {
              toast.error(data.message);
          }
      } catch (error) {
          toast.error(`Erro: ${error.message}`);
      }
  }

  const loadLogsIA = async () => {
    setLoadingLogs(true);
    try {
      const params = { limit: 30 }
      if (logFilterSn) params.order_sn = logFilterSn
      const data = await personalizadosService.getAllLogs(params)
      if (data.success) {
        setLogsIA(data.data.logs || [])
      } else {
        toast.error('Erro ao carregar logs')
      }
    } catch (err) {
      toast.error(`Erro: ${err.message}`)
    } finally {
      setLoadingLogs(false)
    }
  }

  const toggleLogExpand = (logId) => {
    setExpandedLogs(prev => {
      const next = new Set(prev)
      if (next.has(logId)) next.delete(logId)
      else next.add(logId)
      return next
    })
  }

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Ferramentas Administrativas</h1>

      <Tabs defaultValue="import" className="w-full">
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="import">Importação Manual</TabsTrigger>
          <TabsTrigger value="ai">Processamento IA</TabsTrigger>
          <TabsTrigger value="logs">
            <FileText className="w-4 h-4 mr-2" /> Logs IA
          </TabsTrigger>
          <TabsTrigger value="queue">
            <Activity className="w-4 h-4 mr-2" /> Monitor de Fila
          </TabsTrigger>
          <TabsTrigger value="maintenance">Manutenção</TabsTrigger>
        </TabsList>
        
        <TabsContent value="import">
          <Card>
            <CardHeader>
              <CardTitle>Importar Pedido do Bling</CardTitle>
              <CardDescription>
                Importe manualmente um pedido específico do Bling usando o número da loja (Shopee ID).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleImportBlingOrder} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="numero_loja">Número do Pedido na Loja</Label>
                  <Input
                    id="numero_loja"
                    placeholder="Ex: 230815ABC123"
                    value={numeroLoja}
                    onChange={(e) => setNumeroLoja(e.target.value)}
                  />
                </div>
                <Button type="submit" disabled={loadingImport}>
                  {loadingImport && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Upload className="mr-2 h-4 w-4" /> Importar Pedido
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ai">
          <div className="space-y-4">
            {/* Formulário */}
            <Card>
              <CardHeader>
                <CardTitle>Identificação de Nomes via IA</CardTitle>
                <CardDescription>
                  Processe pedidos para identificar nomes para personalização utilizando Inteligência Artificial.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleProcessAINames} className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="limit">Limite de Pedidos (Opcional)</Label>
                      <Input
                        id="limit"
                        type="number"
                        placeholder="Ex: 10"
                        value={aiLimit}
                        onChange={(e) => setAiLimit(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="shopee_order_sn">ID Específico (Opcional)</Label>
                      <Input
                        id="shopee_order_sn"
                        placeholder="Ex: 260410F5YBJSAU"
                        value={aiOrderSn}
                        onChange={(e) => setAiOrderSn(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button type="submit" disabled={isProcessing}>
                      {isProcessing ? <Square className="mr-2 h-4 w-4 animate-pulse" /> : <Play className="mr-2 h-4 w-4" />}
                      {isProcessing ? 'Processando...' : 'Processar com IA'}
                    </Button>
                    {isProcessing && (
                      <Button variant="outline" onClick={() => {
                        setIsProcessing(false);
                        if (pollRef.current) clearInterval(pollRef.current);
                        addLog('Processamento interrompido pelo usuário', 'warning');
                      }}>
                        <Square className="mr-2 h-4 w-4" /> Interromper
                      </Button>
                    )}
                  </div>
                </form>
              </CardContent>
            </Card>

            {/* Terminal de saída em tempo real */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <Terminal className="h-5 w-5" />
                  Console de Execução
                  {isProcessing && (
                    <span className="flex items-center gap-1 text-xs font-normal text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" /> Processando...
                    </span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="bg-gray-950 text-green-400 font-mono text-xs p-4 rounded-b-lg max-h-[500px] overflow-y-auto min-h-[200px]">
                  {processingLogs.length === 0 ? (
                    <div className="text-gray-500 italic">
                      {processingComplete
                        ? `✓ ${processingComplete.message}`
                        : 'Nenhuma execução ainda. Clique em "Processar com IA" para iniciar.'}
                    </div>
                  ) : (
                    <>
                      {processingLogs.map((log, i) => (
                        <div
                          key={i}
                          className={`${
                            log.type === 'error' ? 'text-red-400' :
                            log.type === 'success' ? 'text-green-300' :
                            log.type === 'warning' ? 'text-yellow-400' :
                            'text-green-400'
                          } ${log.message.startsWith('  ') ? 'pl-4' : ''}`}
                        >
                          <span className="text-gray-500">[{log.timestamp}]</span> {log.message}
                        </div>
                      ))}
                      <div ref={logsEndRef} />
                    </>
                  )}
                </div>
                <div className="flex items-center justify-between px-4 py-2 bg-gray-900 text-xs text-gray-400">
                  <span>{processingLogs.length} linha{processingLogs.length !== 1 ? 's' : ''}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-xs text-gray-400 hover:text-white"
                    onClick={() => setProcessingLogs([])}
                  >
                    Limpar
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <CardTitle>Logs de Execução IA</CardTitle>
              <CardDescription>
                Histórico de execuções do processamento de personalização por IA.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex gap-3 mb-4 items-center">
                <Input
                  placeholder="Filtrar por order_sn..."
                  value={logFilterSn}
                  onChange={(e) => setLogFilterSn(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && loadLogsIA()}
                  className="max-w-xs"
                />
                <Button onClick={loadLogsIA} disabled={loadingLogs} size="sm">
                  <Search className="w-4 h-4 mr-2" /> Buscar
                </Button>
                {logsIA.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-red-600 hover:text-red-700 hover:bg-red-50 ml-auto"
                    onClick={async () => {
                      if (logFilterSn) {
                        if (!window.confirm(`Deletar logs do pedido ${logFilterSn}?`)) return;
                        const res = await personalizadosService.deleteLogsBatch({ order_sn: logFilterSn });
                        toast.success(res.message || 'Logs deletados');
                      } else {
                        if (!window.confirm(`Deletar TODOS os ${logsIA.length} logs? Esta ação não pode ser desfeita.`)) return;
                        const res = await personalizadosService.deleteAllLogs();
                        toast.success(res.message || 'Todos os logs deletados');
                      }
                      loadLogsIA();
                    }}
                  >
                    <Trash2 className="w-4 h-4 mr-1" /> Deletar {logFilterSn ? 'Logs do Pedido' : 'Todos Logs'}
                  </Button>
                )}
              </div>

              {loadingLogs ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : logsIA.length === 0 ? (
                <p className="text-center py-8 text-muted-foreground">
                  Nenhum log encontrado. Processe pedidos na aba "Processamento IA" primeiro.
                </p>
              ) : (
                <div className="space-y-2">
                  {logsIA.map((log) => {
                    const isExpanded = expandedLogs.has(log.id)
                    return (
                      <div key={log.id} className="border rounded-lg overflow-hidden">
                        <div
                          className="flex items-center gap-3 px-4 py-3 bg-gray-50 hover:bg-gray-100 cursor-pointer"
                          onClick={() => toggleLogExpand(log.id)}
                        >
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[log.status] || 'bg-gray-100 text-gray-800'}`}>
                            {log.status || 'unknown'}
                          </span>
                          <code className="text-sm font-mono">{log.order_sn}</code>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {log.executed_at ? format(new Date(log.executed_at), 'dd/MM/yyyy HH:mm:ss', { locale: ptBR }) : '-'}
                          </span>
                        </div>
                        {isExpanded && (
                          <div className="px-4 py-3 space-y-2 bg-white">
                            {log.error_message && (
                              <div className="bg-red-50 border border-red-200 rounded p-2">
                                <p className="text-xs font-medium text-red-800">Erro:</p>
                                <pre className="text-xs text-red-700 mt-1 whitespace-pre-wrap">{log.error_message}</pre>
                              </div>
                            )}
                            {log.model_result && (
                              <details>
                                <summary className="text-xs font-medium cursor-pointer">Resultado da IA</summary>
                                <pre className="text-xs bg-gray-50 border rounded p-2 mt-1 overflow-x-auto max-h-48">
                                  {typeof log.model_result === 'string' ? log.model_result : JSON.stringify(log.model_result, null, 2)}
                                </pre>
                              </details>
                            )}
                            {log.extracted_personalization && (
                              <details>
                                <summary className="text-xs font-medium cursor-pointer">Personalizações Extraídas</summary>
                                <pre className="text-xs bg-gray-50 border rounded p-2 mt-1 overflow-x-auto max-h-48">
                                  {typeof log.extracted_personalization === 'string' ? log.extracted_personalization : JSON.stringify(log.extracted_personalization, null, 2)}
                                </pre>
                              </details>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="queue">
          <QueueMonitor />
        </TabsContent>

        <TabsContent value="maintenance">
            <Card>
                <CardHeader>
                    <CardTitle>Manutenção de Produtos</CardTitle>
                    <CardDescription>Ações em massa para correção de dados.</CardDescription>
                </CardHeader>
                <CardContent>
                    <Button 
                        onClick={handleUpdateProductStatus} 
                        variant="outline"
                    >
                        <RefreshCw className="mr-2 h-4 w-4" /> 
                        Atualizar Status de Todos os Produtos para 'Ativo'
                    </Button>
                </CardContent>
            </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default FerramentasPage;
