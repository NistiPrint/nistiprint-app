import QueueMonitor from '@/components/admin/QueueMonitor';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { reprocessamentoService } from '@/services/reprocessamentoService';
import { Activity, Brain, Database, Loader2, RefreshCw, Upload } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

function FerramentasPage() {
  const navigate = useNavigate();
  const [loadingImport, setLoadingImport] = useState(false);
  const [numeroLoja, setNumeroLoja] = useState('');
  
  // Estados para reprocessamento
  const [loadingReprocess, setLoadingReprocess] = useState(false);
  const [pedidoId, setPedidoId] = useState('');
  const [loteIds, setLoteIds] = useState('');
  const [canalVendaId, setCanalVendaId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

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

  const handleReprocessOrder = async (e) => {
    e.preventDefault();
    if (!pedidoId) {
      toast.warning('ID do pedido é obrigatório.');
      return;
    }

    setLoadingReprocess(true);
    try {
      const result = await reprocessamentoService.reprocessOrder(parseInt(pedidoId));
      if (result.success) {
        toast.success(`Pedido ${pedidoId} reprocessado com sucesso. ${result.total_processed} integrações processadas.`);
        setPedidoId('');
      } else {
        toast.error(result.error || 'Erro ao reprocessar pedido');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingReprocess(false);
    }
  };

  const handleReprocessBatch = async (e) => {
    e.preventDefault();
    if (!loteIds) {
      toast.warning('Lista de IDs é obrigatória.');
      return;
    }

    const ids = loteIds.split(',').map(id => id.trim()).filter(id => id);
    if (ids.length === 0) {
      toast.warning('Lista de IDs inválida.');
      return;
    }

    setLoadingReprocess(true);
    try {
      const result = await reprocessamentoService.reprocessBatch(ids);
      if (result.success) {
        toast.success(`Lote reprocessado com sucesso. ${result.total_processed}/${result.total_requested} pedidos processados.`);
        setLoteIds('');
      } else {
        toast.error(result.error || 'Erro ao reprocessar lote');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingReprocess(false);
    }
  };

  const handleReprocessByCanal = async (e) => {
    e.preventDefault();
    if (!canalVendaId) {
      toast.warning('ID do canal é obrigatório.');
      return;
    }

    setLoadingReprocess(true);
    try {
      const dateRange = {};
      if (startDate) dateRange.start_date = startDate;
      if (endDate) dateRange.end_date = endDate;

      const result = await reprocessamentoService.reprocessByCanal(
        parseInt(canalVendaId),
        Object.keys(dateRange).length > 0 ? dateRange : null
      );
      if (result.success) {
        toast.success(`Pedidos do canal ${canalVendaId} reprocessados com sucesso. ${result.total_processed} pedidos processados.`);
        setCanalVendaId('');
        setStartDate('');
        setEndDate('');
      } else {
        toast.error(result.error || 'Erro ao reprocessar pedidos do canal');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingReprocess(false);
    }
  };

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Ferramentas Administrativas</h1>

      <Tabs defaultValue="import" className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="import">Importação Manual</TabsTrigger>
          <TabsTrigger value="queue">
            <Activity className="w-4 h-4 mr-2" /> Monitor de Fila
          </TabsTrigger>
          <TabsTrigger value="reprocess">
            <Database className="w-4 h-4 mr-2" /> Reprocessamento
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

          <Card className="mt-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Brain className="h-5 w-5" />
                IA - Inteligência Artificial
              </CardTitle>
              <CardDescription>
                Gerenciamento de processamento de IA para personalizações
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => navigate('/ferramentas/ia')} className="w-full">
                <Brain className="mr-2 h-4 w-4" />
                Acessar Painel de IA
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="queue">
          <QueueMonitor />
        </TabsContent>

        <TabsContent value="reprocess">
          <div className="space-y-6">
            {/* Reprocessar Pedido Individual */}
            <Card>
              <CardHeader>
                <CardTitle>Reprocessar Pedido Individual</CardTitle>
                <CardDescription>
                  Reprocessa um pedido específico buscando dados atualizados de todas as integrações.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleReprocessOrder} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="pedido_id">ID do Pedido</Label>
                    <Input
                      id="pedido_id"
                      type="number"
                      placeholder="Ex: 4063"
                      value={pedidoId}
                      onChange={(e) => setPedidoId(e.target.value)}
                    />
                  </div>
                  <Button type="submit" disabled={loadingReprocess}>
                    {loadingReprocess && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    <RefreshCw className="mr-2 h-4 w-4" /> Reprocessar Pedido
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Reprocessar Lote */}
            <Card>
              <CardHeader>
                <CardTitle>Reprocessar Lote de Pedidos</CardTitle>
                <CardDescription>
                  Reprocessa múltiplos pedidos de uma vez (separados por vírgula).
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleReprocessBatch} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="lote_ids">IDs dos Pedidos (separados por vírgula)</Label>
                    <textarea
                      id="lote_ids"
                      className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      placeholder="Ex: 4063, 4064, 4065"
                      value={loteIds}
                      onChange={(e) => setLoteIds(e.target.value)}
                    />
                  </div>
                  <Button type="submit" disabled={loadingReprocess}>
                    {loadingReprocess && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    <RefreshCw className="mr-2 h-4 w-4" /> Reprocessar Lote
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Reprocessar por Canal */}
            <Card>
              <CardHeader>
                <CardTitle>Reprocessar por Canal de Venda</CardTitle>
                <CardDescription>
                  Reprocessa todos os pedidos de um canal de venda específico (opcionalmente filtrado por período).
                </CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleReprocessByCanal} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="canal_venda_id">ID do Canal de Venda</Label>
                    <Input
                      id="canal_venda_id"
                      type="number"
                      placeholder="Ex: 1 (Shopee)"
                      value={canalVendaId}
                      onChange={(e) => setCanalVendaId(e.target.value)}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="start_date">Data Início (opcional)</Label>
                      <Input
                        id="start_date"
                        type="date"
                        value={startDate}
                        onChange={(e) => setStartDate(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="end_date">Data Fim (opcional)</Label>
                      <Input
                        id="end_date"
                        type="date"
                        value={endDate}
                        onChange={(e) => setEndDate(e.target.value)}
                      />
                    </div>
                  </div>
                  <Button type="submit" disabled={loadingReprocess}>
                    {loadingReprocess && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    <RefreshCw className="mr-2 h-4 w-4" /> Reprocessar Canal
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
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
