import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Upload, Wand2, RefreshCw, Activity, FileText, Search } from 'lucide-react';
import { toast } from 'sonner';
import QueueMonitor from '@/components/admin/QueueMonitor';
import { personalizadosService } from '@/services/personalizadosService';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

function FerramentasPage() {
  const [loadingImport, setLoadingImport] = useState(false);
  const [loadingAI, setLoadingAI] = useState(false);
  const [numeroLoja, setNumeroLoja] = useState('');
  const [aiLimit, setAiLimit] = useState('');
  const [aiOrderSn, setAiOrderSn] = useState('');

  // Estado para logs de IA
  const [logsIA, setLogsIA] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logFilterSn, setLogFilterSn] = useState('');
  const [expandedLogs, setExpandedLogs] = useState(new Set());

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
    setLoadingAI(true);
    try {
      const response = await fetch('/api/v2/ferramentas/processar_nomes_ia', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          limit: aiLimit,
          shopee_order_sn: aiOrderSn,
        }),
      });

      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
      } else {
        toast.error(data.message || 'Erro ao processar nomes com IA.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingAI(false);
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

  const STATUS_COLORS = {
    success: 'bg-green-100 text-green-800',
    error: 'bg-red-100 text-red-800',
    db_error: 'bg-orange-100 text-orange-800',
    no_response: 'bg-yellow-100 text-yellow-800',
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
                      placeholder="Ex: 230815ABC123"
                      value={aiOrderSn}
                      onChange={(e) => setAiOrderSn(e.target.value)}
                    />
                  </div>
                </div>
                <Button type="submit" disabled={loadingAI}>
                  {loadingAI && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  <Wand2 className="mr-2 h-4 w-4" /> Processar com IA
                </Button>
              </form>
            </CardContent>
          </Card>
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
              <div className="flex gap-3 mb-4">
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
