import { ChatSidebar } from '@/components/chat/ChatSidebar';
import OrderCard from '@/components/vendas/OrderCard';
import OrderFilters from '@/components/vendas/OrderFilters';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Brain, Flag, Loader2, RefreshCw, Settings } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom';
import { toast } from 'sonner';

const apiRoot = '/api/v2/mercadolivre/integracoes';

async function api(path, options = {}) {
  const response = await fetch(`${apiRoot}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json();
  if (!response.ok || body.success === false) throw new Error(body.message || 'Falha na operação');
  return body.data;
}

function AccountList() {
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    api('/personalizacoes').then(data => setAccounts(data.accounts || [])).catch(err => setError(err.message));
  }, []);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Pedidos do Mercado Livre</h2>
          <p className="mt-1 text-sm text-muted-foreground">Escolha uma conta para consultar pedidos e conversas.</p>
        </div>
        <Link to="/configuracoes/ia" className="rounded border px-3 py-2 text-sm hover:bg-muted">Configuração de IA</Link>
      </div>
      {error && <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {!accounts.length && !error && <p className="rounded border p-4 text-sm">Nenhuma conta Mercado Livre conectada.</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map(account => (
          <Link key={account.integration_id} to={`/vendas/personalizadas/mercadolivre/${account.integration_id}`}
            className="rounded-lg border bg-card p-5 shadow-sm transition hover:border-primary">
            <h3 className="font-semibold">{account.name}</h3>
            <p className="mt-1 text-sm text-muted-foreground">Conta {account.account_user_id || account.integration_id}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

function normalizeOrder(order) {
  const externalId = order.external_order_id || order.marketplace_order_id || order.codigo_pedido_externo;
  return {
    ...order,
    marketplace: 'mercadolivre',
    // OrderCard is shared with Shopee and reads the buyer and item fields
    // from the canonical card shape. Keep these aliases here so a new chat
    // message can mark the order pending without hiding its previous result.
    numero: order.numero_pedido || externalId,
    numeroLoja: externalId,
    data: order.data_venda,
    contato: { nome: order.cliente_nome || order.buyer_username || '' },
    shopee: { username: order.buyer_username || '', message: order.message_to_seller || '' },
    itens: (order.items || []).map(item => ({
      ...item,
      codigo: item.sku_externo,
      descricao: item.titulo_anuncio || item.descricao,
      personalizations: (item.personalizations || []).map(value => ({
        ...value,
        name_source_message_id: value.name_source_message_id || value.details?.name_source_message_id,
        initial_source_message_id: value.initial_source_message_id || value.details?.initial_source_message_id,
      })),
    })),
  };
}

const personalizationHasName = row => Boolean(
  row?.customization_name?.trim() || row?.customization_initial?.trim(),
);

const orderHasIdentifiedName = order => order.itens.some(item =>
  item.personalizations.some(personalizationHasName),
);

function AccountOrders({ integrationId }) {
  const navigate = useNavigate();
  const outletContext = useOutletContext() || {};
  const [account, setAccount] = useState(outletContext.account || null);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [aiFilter, setAiFilter] = useState('');
  const [chatFilter, setChatFilter] = useState('');
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0, has_next: false });
  const [statusCounts, setStatusCounts] = useState({ pendente_ia: 0, com_chat: 0, sem_chat: 0, nome_identificado: 0, sem_nome: 0 });
  const [submittingExtraction, setSubmittingExtraction] = useState(false);
  const [selectedChatOrder, setSelectedChatOrder] = useState(null);
  const [highlightedMessages, setHighlightedMessages] = useState([]);
  const [selectedOrderForLogs, setSelectedOrderForLogs] = useState(null);
  const [aiLogs, setAiLogs] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [selectedOrderForFeedback, setSelectedOrderForFeedback] = useState(null);
  const [feedbackNotes, setFeedbackNotes] = useState('');
  const refresh = useCallback(async (signal) => {
    const query = new URLSearchParams({ page: String(page), page_size: '20' });
    if (debouncedSearch) query.set('search', debouncedSearch);
    if (aiFilter) query.set('ai_filter', aiFilter);
    if (chatFilter) query.set('chat_filter', chatFilter);
    const result = await api(`/${integrationId}/personalizados/pedidos?${query}`, { signal });
    setOrders(current => page === 1
      ? (result.orders || []).map(normalizeOrder)
      : [...new Map([...current, ...(result.orders || []).map(normalizeOrder)].map(order => [order.id, order])).values()]);
    setPagination(result.pagination || { page, page_size: 20, total: 0, has_next: false });
    if (result.status_counts) setStatusCounts(result.status_counts);
    setError('');
  }, [integrationId, page, debouncedSearch, aiFilter, chatFilter]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  useEffect(() => { setPage(1); }, [debouncedSearch, aiFilter, chatFilter]);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setRefreshing(true);
    refresh(controller.signal).catch(err => {
      if (!cancelled && err.name !== 'AbortError') setError(err.message);
    }).finally(() => {
      if (cancelled) return;
      setLoading(false);
      setRefreshing(false);
    });
    return () => { cancelled = true; controller.abort(); };
  }, [refresh, page, debouncedSearch, aiFilter, chatFilter]);

  useEffect(() => {
    if (outletContext.account) setAccount(outletContext.account);
  }, [outletContext.account]);

  useEffect(() => {
    const onBatch = event => {
      if (event.detail?.integrationId && String(event.detail.integrationId) !== String(integrationId)) return;
      setPage(1);
      refresh().catch(err => setError(err.message));
    };
    window.addEventListener('activity:mercadolivre-batch', onBatch);
    window.addEventListener('online', onBatch);
    return () => {
      window.removeEventListener('activity:mercadolivre-batch', onBatch);
      window.removeEventListener('online', onBatch);
    };
  }, [integrationId, refresh]);

  const filteredOrders = orders;

  const startExtraction = async (pedidoIds, force = false) => {
    if (submittingExtraction) return;
    setSubmittingExtraction(true);
    try {
      const result = await api(`/${integrationId}/personalizados/extrair`, {
        method: 'POST', body: JSON.stringify({ ...(pedidoIds ? { pedido_ids: [pedidoIds] } : {}), force, limit: 50 }),
      });
      if (!result.batch_id) {
        toast.success(result.message || 'Não há pedidos pendentes para extrair.');
        return;
      }
      toast.success('Extração iniciada. Acompanhe o andamento no sininho.');
    } catch (err) { toast.error(err.message); }
    finally { setSubmittingExtraction(false); }
  };

  const openChat = (_username, _orderNumber, order) => {
    setHighlightedMessages(order.itens.flatMap(item => item.personalizations.flatMap(value => [
      value.name_source_message_id, value.initial_source_message_id,
    ].filter(Boolean))));
    setSelectedChatOrder(order);
  };

  const openLogs = async (_externalOrderId, order) => {
    setSelectedOrderForLogs(order);
    setAiLogs([]);
    setLoadingLogs(true);
    try {
      const data = await api(`/${integrationId}/personalizados/pedidos/${order.id}/logs`);
      setAiLogs(data.logs || []);
    } catch (err) { toast.error(err.message); }
    finally { setLoadingLogs(false); }
  };

  const deleteLogs = async () => {
    if (!selectedOrderForLogs || !window.confirm('Deletar todos os logs deste pedido?')) return;
    try {
      const result = await api(`/${integrationId}/personalizados/pedidos/${selectedOrderForLogs.id}/logs`, { method: 'DELETE' });
      setAiLogs([]);
      toast.success(result.message || 'Logs deletados.');
    } catch (err) { toast.error(err.message); }
  };

  const submitFeedback = async () => {
    if (!selectedOrderForFeedback) return;
    try {
      await api(`/${integrationId}/personalizados/pedidos/${selectedOrderForFeedback.id}/feedback`, {
        method: 'POST', body: JSON.stringify({ texto_feedback: feedbackNotes }),
      });
      setSelectedOrderForFeedback(null);
      toast.success('Obrigado pelo relato. Vamos analisar o ocorrido.');
    } catch (err) { toast.error(err.message); }
  };

  if (loading && !orders.length) return <div className="flex justify-center p-8"><Loader2 className="h-8 w-8 animate-spin" /></div>;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button onClick={() => navigate('/vendas/personalizadas/mercadolivre')} className="mb-2 text-sm text-muted-foreground">← Contas Mercado Livre</button>
          <h2 className="text-xl font-semibold">{account?.name || `Conta ${integrationId}`}</h2>
          <p className="text-sm text-muted-foreground">Pedidos personalizados · Mercado Livre</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="rounded border px-3 py-2 text-sm" to={`/configuracoes/integracoes/${integrationId}/ia`}><Settings className="mr-1 inline h-4 w-4" />Configuração IA</Link>
          <Button variant="outline" onClick={() => startExtraction(null, false)} disabled={submittingExtraction}>
            <Brain className="mr-2 h-4 w-4" /> Extrair nomes pendentes
          </Button>
        </div>
      </div>
      {error && <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error} <Button variant="link" onClick={() => refresh().catch(err => setError(err.message))}>Tentar novamente</Button></p>}
      {refreshing && orders.length > 0 && <p role="status" className="text-xs text-muted-foreground">Atualizando pedidos…</p>}

      <Card className="shadow-sm">
        <CardHeader className="pb-3"><CardTitle className="text-sm font-medium text-muted-foreground">Filtrar pedidos</CardTitle></CardHeader>
        <CardContent className="p-0">
          <OrderFilters searchTerm={searchTerm} onSearchChange={setSearchTerm}
            aiFilter={aiFilter} onAiFilterChange={value => setAiFilter(current => current === value ? '' : value)}
            chatFilter={chatFilter} onChatFilterChange={value => setChatFilter(current => current === value ? '' : value)}
            statusCounts={statusCounts} />
          {!filteredOrders.length ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Não há pedidos personalizados disponíveis para estes filtros.</div>
          ) : (
            <div className="space-y-4 bg-white p-4 md:p-6">
              {filteredOrders.map(order => (
                <OrderCard key={order.id} order={order}
                  onOpenChat={openChat}
                  onOpenAiLogs={openLogs}
                  onProcessAI={(_externalId, force) => startExtraction(order.id, force)}
                  onReportProblem={(_externalId, selected) => { setFeedbackNotes(''); setSelectedOrderForFeedback(selected); }} />
              ))}
              {pagination.has_next && (
                <div className="flex justify-center pt-3"><Button variant="outline" disabled={refreshing} onClick={() => setPage(value => value + 1)}>Carregar mais ({Math.max(0, pagination.total - orders.length)} restantes)</Button></div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <ChatSidebar open={!!selectedChatOrder} onOpenChange={open => { if (!open) setSelectedChatOrder(null); }}
        username={selectedChatOrder?.buyer_username || 'Comprador Mercado Livre'}
        orderId={selectedChatOrder?.external_order_id} marketplace="mercadolivre"
        integrationId={integrationId} pedidoId={selectedChatOrder?.id}
        highlightedMessageIds={highlightedMessages} />

      <Dialog open={!!selectedOrderForLogs} onOpenChange={open => { if (!open) setSelectedOrderForLogs(null); }}>
        <DialogContent className="max-h-[80vh] max-w-4xl overflow-y-auto">
          <DialogHeader><DialogTitle className="flex items-center justify-between gap-2">
            <span>Logs de execução da IA · Pedido {selectedOrderForLogs?.external_order_id}</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={loadingLogs} onClick={() => openLogs(null, selectedOrderForLogs)}><RefreshCw className="mr-1 h-3 w-3" />Atualizar</Button>
              {!!aiLogs.length && <Button variant="outline" size="sm" onClick={deleteLogs}>Deletar logs</Button>}
            </div>
          </DialogTitle></DialogHeader>
          {loadingLogs ? (
            <div className="flex justify-center p-8"><Loader2 className="h-7 w-7 animate-spin" /></div>
          ) : !aiLogs.length ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Nenhum log de execução encontrado para este pedido.</p>
          ) : (
            <div className="space-y-3">{aiLogs.map(log => (
              <Card key={log.id}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center justify-between text-sm">
                    <span>{log.status}</span>
                    <Badge variant={['success', 'no_personalization_found'].includes(log.status) ? 'default' : 'destructive'}>{log.status}</Badge>
                  </CardTitle>
                  <p className="text-xs text-muted-foreground">{log.executed_at ? new Date(log.executed_at).toLocaleString('pt-BR') : ''}</p>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  {log.error_message && <p className="text-red-700">{log.error_message}</p>}
                  {log.model_result && <details><summary className="cursor-pointer">Resultado da IA</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{JSON.stringify(log.model_result, null, 2)}</pre></details>}
                  {log.input_data && <details><summary className="cursor-pointer">Dados enviados ({log.input_data.length} caracteres)</summary><pre className="mt-2 whitespace-pre-wrap text-xs">{log.input_data}</pre></details>}
                </CardContent>
              </Card>
            ))}</div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!selectedOrderForFeedback} onOpenChange={open => { if (!open) setSelectedOrderForFeedback(null); }}>
        <DialogContent className="max-w-md"><DialogHeader><DialogTitle className="flex items-center gap-2"><Flag className="h-5 w-5 text-red-500" />Relatar problema · {selectedOrderForFeedback?.external_order_id}</DialogTitle></DialogHeader>
          <label className="block text-sm font-medium">Descreva o problema encontrado neste pedido:<Textarea value={feedbackNotes} onChange={event => setFeedbackNotes(event.target.value)} rows={4} className="mt-2" /></label>
          <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setSelectedOrderForFeedback(null)}>Cancelar</Button><Button variant="destructive" disabled={!feedbackNotes.trim()} onClick={submitFeedback}>Enviar relato</Button></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function MercadoLivrePersonalizacoesPage() {
  const { integration_id: integrationId } = useParams();
  return integrationId ? <AccountOrders integrationId={integrationId} /> : <AccountList />;
}
