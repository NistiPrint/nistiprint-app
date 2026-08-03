import QueueMonitor from '@/components/admin/QueueMonitor';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { reprocessamentoService } from '@/services/reprocessamentoService';
import { Activity, AlertTriangle, Brain, Database, Loader2, RefreshCw, Undo2, Upload } from 'lucide-react';
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

  // Corte histórico: marcar pedidos pendentes travados como entregues.
  // Fluxo em dois passos deliberado — prévia primeiro, aplicar depois — porque
  // a ação altera o status de milhares de pedidos de uma vez. Cancelado,
  // Entregue e Devolvido são situações finais e nunca são tocados.
  const [dataCorte, setDataCorte] = useState('');
  const [previa, setPrevia] = useState(null);
  const [loadingCorte, setLoadingCorte] = useState(false);
  const [ultimoLote, setUltimoLote] = useState(null);

  const chamarCorte = async (dryRun) => {
    if (!dataCorte) {
      toast.warning('Informe a data de corte.');
      return null;
    }
    setLoadingCorte(true);
    try {
      const response = await fetch('/api/v2/ferramentas/marcar-entregues-ate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ data: dataCorte, dry_run: dryRun }),
      });
      const data = await response.json();
      if (!data.success) {
        toast.error(data.message || 'Erro na operação.');
        return null;
      }
      return data;
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
      return null;
    } finally {
      setLoadingCorte(false);
    }
  };

  const handlePreviaCorte = async () => {
    setUltimoLote(null);
    const data = await chamarCorte(true);
    if (data) {
      setPrevia(data);
      if (!data.total) toast.info(data.message);
    }
  };

  const handleAplicarCorte = async () => {
    const total = previa?.total || 0;
    if (!confirm(
      `Isso marcará ${total} pedidos pendentes (Em Aberto, Em Andamento, Produzido, ` +
      `Pronto para Envio, Enviado) como "Entregue" e os removerá da torre de despacho.\n\n` +
      `Pedidos Cancelados, Entregues e Devolvidos dentro do período não são afetados — ` +
      `são situações finais.\n\nA ação pode ser desfeita logo em seguida. Continuar?`
    )) return;

    const data = await chamarCorte(false);
    if (data) {
      toast.success(data.message);
      setUltimoLote(data.lote);
      setPrevia(null);
    }
  };

  const handleDesfazerCorte = async () => {
    if (!ultimoLote) return;
    setLoadingCorte(true);
    try {
      const response = await fetch('/api/v2/ferramentas/desfazer-lote-manutencao', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ lote: ultimoLote }),
      });
      const data = await response.json();
      if (data.success) {
        toast.success(data.message);
        setUltimoLote(null);
      } else {
        toast.error(data.message || 'Erro ao desfazer.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingCorte(false);
    }
  };

  // Ressincronização a partir da origem do ingest.
  const [contas, setContas] = useState([]);
  const [contasCarregadas, setContasCarregadas] = useState(false);
  const [dias, setDias] = useState('7');
  const [limite, setLimite] = useState('');
  const [ressyncEmAndamento, setRessyncEmAndamento] = useState(null);
  const [ressyncResultado, setRessyncResultado] = useState(null);

  const carregarContas = async () => {
    try {
      const response = await fetch('/api/v2/ferramentas/ressincronizar/contas', {
        headers: { Accept: 'application/json' },
      });
      const data = await response.json();
      if (data.success) {
        setContas(data.data || []);
        setContasCarregadas(true);
      } else {
        toast.error(data.message || 'Erro ao carregar contas.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    }
  };

  const handleRessincronizar = async (conta) => {
    setRessyncEmAndamento(conta.integration_id);
    setRessyncResultado(null);
    try {
      const response = await fetch('/api/v2/ferramentas/ressincronizar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          integration_id: conta.integration_id,
          dias: parseInt(dias, 10) || 7,
          limite: limite ? parseInt(limite, 10) : null,
        }),
      });
      const data = await response.json();
      if (data.success) {
        toast.success(`${conta.nome}: ${data.message}`);
        setRessyncResultado({ conta: conta.nome, ...data.data });
      } else {
        toast.error(data.message || 'Erro na ressincronização.');
      }
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setRessyncEmAndamento(null);
    }
  };

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
          <TabsTrigger value="reprocess">
            <Database className="w-4 h-4 mr-2" /> Reprocessamento
          </TabsTrigger>
          <TabsTrigger value="ressync">Ressincronizar</TabsTrigger>
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

        <TabsContent value="ressync">
            <Card>
                <CardHeader>
                    <CardTitle>Ressincronizar a partir da origem</CardTitle>
                    <CardDescription>
                        Relê os pedidos pendentes direto no marketplace e reprocessa pela pipeline
                        normal de ingest. Use quando a base estiver defasada ou incoerente.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-4">
                        <div className="space-y-2 w-32">
                            <Label htmlFor="ressyncDias">Últimos dias</Label>
                            <Input
                                id="ressyncDias"
                                type="number"
                                min="1"
                                value={dias}
                                onChange={(e) => setDias(e.target.value)}
                            />
                        </div>
                        <div className="space-y-2 w-40">
                            <Label htmlFor="ressyncLimite">Limite (opcional)</Label>
                            <Input
                                id="ressyncLimite"
                                type="number"
                                min="1"
                                placeholder="sem limite"
                                value={limite}
                                onChange={(e) => setLimite(e.target.value)}
                            />
                        </div>
                    </div>

                    {!contasCarregadas ? (
                        <Button onClick={carregarContas} variant="outline">
                            <RefreshCw className="mr-2 h-4 w-4" />
                            Carregar contas de marketplace
                        </Button>
                    ) : (
                        <div className="space-y-2">
                            {contas.length === 0 && (
                                <p className="text-sm text-muted-foreground">
                                    Nenhuma conta de marketplace ativa encontrada.
                                </p>
                            )}
                            {contas.map((conta) => (
                                <div
                                    key={conta.integration_id}
                                    className="flex items-center justify-between gap-3 rounded-md border p-3"
                                >
                                    <div className="min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-sm">{conta.nome}</span>
                                            <span className={`text-[10px] rounded-full px-2 py-0.5 ${
                                                conta.rota === 'direta'
                                                    ? 'bg-green-100 text-green-800'
                                                    : 'bg-blue-100 text-blue-800'
                                            }`}>
                                                {conta.rota === 'direta' ? 'API própria' : 'via Bling'}
                                            </span>
                                        </div>
                                        <p className="text-xs text-muted-foreground mt-0.5">
                                            {conta.module_id}
                                            {conta.shop_id ? ` · shop_id ${conta.shop_id}` : ''}
                                        </p>
                                    </div>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={ressyncEmAndamento !== null}
                                        onClick={() => handleRessincronizar(conta)}
                                    >
                                        {ressyncEmAndamento === conta.integration_id ? (
                                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        ) : (
                                            <RefreshCw className="mr-2 h-4 w-4" />
                                        )}
                                        Ressincronizar
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}

                    {ressyncResultado && (
                        <div className="rounded-md border p-3 text-sm space-y-1">
                            <p className="font-medium">{ressyncResultado.conta}</p>
                            <p className="text-muted-foreground">
                                {ressyncResultado.listados} listados na origem ·{' '}
                                {ressyncResultado.processados} reprocessados ·{' '}
                                {ressyncResultado.total_erros || 0} erros
                            </p>
                            {ressyncResultado.erros?.length > 0 && (
                                <ul className="text-xs text-destructive mt-2 space-y-0.5">
                                    {ressyncResultado.erros.map((err) => (
                                        <li key={err.externo}>{err.externo}: {err.erro}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    )}
                </CardContent>
            </Card>
        </TabsContent>

        <TabsContent value="maintenance" className="space-y-4">
            <Card>
                <CardHeader>
                    <CardTitle>Corte histórico de pedidos</CardTitle>
                    <CardDescription>
                        Marca pedidos pendentes travados por falta de atualização como "Entregue" e os
                        remove da torre de despacho. Use para limpar o histórico que aparece como backlog aberto.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                        <div className="flex items-start gap-2">
                            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                            <div>
                                <p className="font-medium">Altera situação de pedidos pendentes</p>
                                <p className="text-xs mt-1">
                                    Pedidos ainda <strong>pendentes</strong> (Em Aberto, Em Andamento, Produzido,
                                    Pronto para Envio, Enviado) no período passam a "Entregue" — presunção de que
                                    a situação nunca foi atualizada. <strong>Cancelados</strong>, <strong>Entregues</strong> e{' '}
                                    <strong>Devolvidos</strong> são situações finais e não são tocados.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-2 max-w-xs">
                        <Label htmlFor="dataCorte">Marcar pedidos com data de venda até</Label>
                        <Input
                            id="dataCorte"
                            type="date"
                            value={dataCorte}
                            onChange={(e) => { setDataCorte(e.target.value); setPrevia(null); }}
                        />
                    </div>

                    {previa && previa.total > 0 && (
                        <div className="rounded-md border p-3 text-sm">
                            <p className="font-medium mb-2">
                                {previa.total} pedidos serão marcados como Entregue:
                            </p>
                            <ul className="space-y-1 text-muted-foreground">
                                {previa.detalhes.map((d) => (
                                    <li key={d.situacao_anterior} className="flex justify-between max-w-xs">
                                        <span>{d.situacao_anterior}</span>
                                        <span className="font-medium text-foreground">{d.quantidade}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    <div className="flex flex-wrap gap-2">
                        <Button onClick={handlePreviaCorte} variant="outline" disabled={loadingCorte || !dataCorte}>
                            {loadingCorte ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Database className="mr-2 h-4 w-4" />}
                            Ver prévia
                        </Button>
                        {previa && previa.total > 0 && (
                            <Button onClick={handleAplicarCorte} variant="destructive" disabled={loadingCorte}>
                                {loadingCorte ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                                Aplicar em {previa.total} pedidos
                            </Button>
                        )}
                        {ultimoLote && (
                            <Button onClick={handleDesfazerCorte} variant="outline" disabled={loadingCorte}>
                                <Undo2 className="mr-2 h-4 w-4" />
                                Desfazer último corte
                            </Button>
                        )}
                    </div>

                    {ultimoLote && (
                        <p className="text-xs text-muted-foreground">
                            Lote {ultimoLote} — o estado anterior foi salvo e pode ser restaurado.
                        </p>
                    )}
                </CardContent>
            </Card>

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
