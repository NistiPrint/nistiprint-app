import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
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
    <main className="mx-auto max-w-5xl space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Personalizações · Mercado Livre</h1>
        <p className="mt-1 text-sm text-muted-foreground">Escolha a conta para consultar pedidos, mensagens privadas e extrações.</p>
      </div>
      <div className="flex flex-wrap gap-2"><Link to="/configuracoes/ia" className="rounded border px-3 py-2 text-sm hover:bg-muted">Configuração de IA</Link></div>
      {error && <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {!accounts.length && !error && <p className="rounded border p-4 text-sm">Nenhuma conta Mercado Livre conectada.</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map(account => (
          <Link key={account.integration_id} to={`/vendas/personalizadas/mercadolivre/${account.integration_id}`}
            className="rounded-lg border bg-card p-5 shadow-sm transition hover:border-primary">
            <h2 className="font-semibold">{account.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">Conta {account.account_user_id || account.integration_id}</p>
            <p className="mt-3 text-xs text-muted-foreground">Abrir pedidos desta conta →</p>
          </Link>
        ))}
      </div>
    </main>
  );
}

function OrderCard({ integrationId, order, refresh }) {
  const [chat, setChat] = useState(null);
  const [logs, setLogs] = useState(null);
  const [busy, setBusy] = useState(false);
  const openChat = async () => {
    try {
      const result = await api(`/${integrationId}/personalizados/pedidos/${order.id}/chat`);
      setChat(result);
    } catch (error) { toast.error(error.message); }
  };
  const save = async (event, item, personalization) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    values.item_pedido_id = item.id;
    values.quantity_to_personalize = Number(values.quantity_to_personalize || 1);
    setBusy(true);
    try {
      const path = personalization
        ? `/${integrationId}/personalizados/personalizacoes/${personalization.id}/confirmar`
        : `/${integrationId}/personalizados/pedidos/${order.id}/personalizacoes`;
      await api(path, { method: 'POST', body: JSON.stringify(values) });
      toast.success('Personalização confirmada.');
      await refresh();
    } catch (error) { toast.error(error.message); }
    finally { setBusy(false); }
  };
  const allPersonalizations = (order.items || []).flatMap(item => item.personalizations?.length
    ? item.personalizations.map(value => ({ item, value }))
    : item.personalization ? [{ item, value: item.personalization }] : []);
  const needsReview = allPersonalizations.some(({ value }) => value.status !== 'SUCCESS');
  return (
    <article className="rounded-lg border bg-card p-4 shadow-sm">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Pedido {order.numero_pedido || order.external_order_id}</h2>
          <p className="text-sm text-muted-foreground">Origem {order.external_order_id} · {order.cliente_nome || 'Comprador Mercado Livre'}</p>
          <p className="mt-1 text-sm text-muted-foreground">{allPersonalizations.length
            ? needsReview ? 'Precisa de revisão' : 'Personalizado'
            : order.has_chat_messages ? 'Aguardando extração' : 'Aguardando mensagem'}</p>
        </div>
        <div className="flex gap-2">
          <button className="rounded border px-3 py-1.5 text-sm" onClick={openChat}>Ver conversa</button>
          <button className="rounded border px-3 py-1.5 text-sm" onClick={async () => {
            try {
              const data = await api(`/${integrationId}/personalizados/pedidos/${order.id}/logs`);
              setLogs(data.logs || []);
            } catch (error) { toast.error(error.message); }
          }}>Ver logs</button>
        </div>
      </header>
      <div className="mt-4 space-y-3">
        {order.items?.map(item => {
          const rows = item.personalizations?.length ? item.personalizations : (item.personalization ? [item.personalization] : []);
          const forms = [...rows, null];
          const remainingQuantity = Math.max(1, Number(item.quantidade || 1) - rows.reduce((sum, row) => sum + Number(row.quantity_to_personalize || 0), 0));
          return (
            <div key={item.id} className="space-y-2 rounded-md bg-muted/40 p-3">
              <div>
                <p className="text-sm font-medium">{item.titulo_anuncio || item.descricao} {item.variacao_externa ? `· ${item.variacao_externa}` : ''}</p>
                <p className="text-xs text-muted-foreground">SKU {item.sku_externo || '—'} · quantidade {item.quantidade}</p>
              </div>
              {forms.map((value, index) => <details key={value?.id || `new-${item.id}-${index}`} className="rounded border bg-background p-2">
                <summary className="cursor-pointer text-sm">
                  {value ? <span className={value.status === 'SUCCESS' ? 'text-green-700' : 'text-amber-700'}>{value.customization_name || 'Sem nome'}{value.customization_initial ? ` · ${value.customization_initial}` : ''} · {value.quantity_to_personalize || 1} un. · {value.status === 'SUCCESS' ? 'Pronto para impressão' : 'Revisar'}</span> : <span className="text-muted-foreground">Adicionar personalização manual</span>}
                </summary>
                <form onSubmit={event => save(event, item, value)} className="mt-3 grid gap-2 md:grid-cols-[1fr_1fr_100px_auto] md:items-end">
                <div className="md:col-span-4 text-xs">
                  <span className={value?.status === 'SUCCESS' ? 'text-green-700' : 'text-amber-700'}>{value?.status === 'SUCCESS' ? 'Extração concluída' : value ? 'Requer revisão' : rows.length ? 'Adicionar outra personalização' : 'Aguardando extração ou revisão'}</span>
                </div>
                <label className="text-xs">Nome<input name="customization_name" defaultValue={value?.customization_name || ''} className="mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm" /></label>
                <label className="text-xs">Inicial<input name="customization_initial" defaultValue={value?.customization_initial || ''} className="mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm" /></label>
                <label className="text-xs">Unidades<input name="quantity_to_personalize" type="number" min="1" max={item.quantidade || 1} defaultValue={value?.quantity_to_personalize || (rows.length && !value ? remainingQuantity : item.quantidade) || 1} className="mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm" /></label>
                <button disabled={busy} className="rounded bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50">{value ? 'Confirmar' : 'Salvar'}</button>
                </form>
              </details>)}
            </div>
          );
        })}
      </div>
      {logs && <section className="mt-4 rounded border p-3">
        <div className="flex justify-between"><h3 className="font-medium">Histórico de extração e revisão</h3><button onClick={() => setLogs(null)}>Fechar</button></div>
        {!logs.length && <p className="py-2 text-sm text-muted-foreground">Nenhum registro ainda.</p>}
        <div className="mt-2 space-y-2">{logs.map(log => <div key={log.id} className="rounded bg-muted p-2 text-xs"><div className="flex justify-between"><strong>{log.status}</strong><span>{log.executed_at}</span></div>{log.error_message && <p className="mt-1 text-red-700">{log.error_message}</p>}{log.metadata?.confirmed_by && <p className="mt-1">Confirmado pelo usuário {log.metadata.confirmed_by}</p>}</div>)}</div>
      </section>}
      {chat && <section className="mt-4 rounded border p-3" aria-live="polite">
        <div className="flex justify-between"><h3 className="font-medium">Mensagens privadas do pacote</h3><button onClick={() => setChat(null)} aria-label="Fechar conversa">Fechar</button></div>
        {!chat.messages?.length && <p className="py-3 text-sm text-muted-foreground">Ainda não há conversa sincronizada para este pedido.</p>}
        <div className="mt-2 max-h-72 space-y-2 overflow-auto">
          {chat.messages?.map(message => <div key={message.provider_message_id} className="rounded bg-muted p-2 text-sm">
            <div className="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ buyer: 'Comprador', seller: 'Vendedor', agent: 'Atendimento Mercado Livre', unknown: 'Participante' }[message.sender_role] || 'Participante'}</span><span>{message.created_at ? new Date(message.created_at).toLocaleString('pt-BR') : ''}</span></div>
            <p className="whitespace-pre-wrap">{message.text_content || (message.attachments?.length ? `${message.attachments.length} anexo(s) — revisão manual necessária` : 'Mensagem sem texto')}</p>
          </div>)}
        </div>
      </section>}
    </article>
  );
}

function AccountOrders({ integrationId }) {
  const navigate = useNavigate();
  const [account, setAccount] = useState(null);
  const [orders, setOrders] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState('');
  const storageKey = `mercadolivre-personalizacao:${integrationId}:batch`;
  const refresh = useCallback(async () => {
    const [accounts, result] = await Promise.all([
      api('/personalizacoes'), api(`/${integrationId}/personalizados/pedidos`),
    ]);
    const selected = (accounts.accounts || []).find(row => String(row.integration_id) === String(integrationId));
    if (!selected) throw new Error('Conta Mercado Livre não encontrada.');
    setAccount(selected);
    setOrders(result.orders || []);
  }, [integrationId]);
  useEffect(() => {
    refresh().catch(err => setError(err.message)).finally(() => setLoading(false));
    try { setBatch(JSON.parse(localStorage.getItem(storageKey) || 'null')); } catch { setBatch(null); }
  }, [refresh, storageKey]);
  useEffect(() => {
    if (!batch?.batch_id || ['COMPLETED', 'FAILED'].includes(batch.status)) return undefined;
    const timer = setInterval(async () => {
      try {
        const current = await api(`/${integrationId}/personalizados/lotes/${batch.batch_id}`);
        setBatch(current);
        localStorage.setItem(storageKey, JSON.stringify(current));
        if (['COMPLETED', 'FAILED'].includes(current.status)) await refresh();
      } catch { /* uma falha pontual não encerra o acompanhamento */ }
    }, 5000);
    return () => clearInterval(timer);
  }, [batch, integrationId, refresh, storageKey]);
  const startExtraction = async (force = false) => {
    try {
      const result = await api(`/${integrationId}/personalizados/extrair`, {
        method: 'POST', body: JSON.stringify({ force }),
      });
      if (result.batch_id) {
        const created = { batch_id: result.batch_id, status: 'PENDING', total: result.total, processed: 0 };
        setBatch(created); localStorage.setItem(storageKey, JSON.stringify(created));
      }
      toast.success(result.message || 'Extração iniciada.');
    } catch (err) { toast.error(err.message); }
  };
  if (loading) return <main className="p-6">Carregando pedidos da conta…</main>;
  return (
    <main className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button onClick={() => navigate('/vendas/personalizadas/mercadolivre')} className="mb-2 text-sm text-muted-foreground">← Contas Mercado Livre</button>
          <h1 className="text-2xl font-semibold">Personalizações · {account?.name || `Conta ${integrationId}`}</h1>
          <p className="text-sm text-muted-foreground">ID da conta conectada: {integrationId}</p>
        </div>
        <div className="flex gap-2">
          <Link className="rounded border px-3 py-2 text-sm" to={`/configuracoes/ia?integration_id=${integrationId}`}>Configuração de IA</Link>
          <button onClick={() => startExtraction(false)} className="rounded bg-primary px-3 py-2 text-sm text-primary-foreground">Extrair pendentes</button>
          <button onClick={() => startExtraction(true)} className="rounded border px-3 py-2 text-sm">Reprocessar</button>
        </div>
      </div>
      {error && <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {batch && <p className="rounded border p-3 text-sm">Lote {batch.status} · {batch.processed || 0}/{batch.total || 0} pacotes</p>}
      <div className="flex flex-wrap gap-2 rounded-lg border bg-card p-3">
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Buscar pedido ou comprador" className="min-w-56 flex-1 rounded border bg-background px-3 py-2 text-sm" />
        <select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="rounded border bg-background px-3 py-2 text-sm">
          <option value="all">Todos os pedidos</option><option value="review">Precisa de revisão</option><option value="ready">Personalizado</option><option value="waiting">Aguardando mensagem ou extração</option>
        </select>
      </div>
      {!orders.length && !error && <p className="rounded border p-4 text-sm">Não há pedidos personalizados em andamento ou prontos para envio nesta conta.</p>}
      <div className="space-y-4">{orders.filter(order => {
        const text = `${order.numero_pedido || ''} ${order.external_order_id || ''} ${order.cliente_nome || ''}`.toLowerCase();
        if (search && !text.includes(search.toLowerCase())) return false;
        const rows = (order.items || []).flatMap(item => item.personalizations?.length ? item.personalizations : item.personalization ? [item.personalization] : []);
        const review = rows.some(row => row.status !== 'SUCCESS');
        const ready = rows.length > 0 && !review;
        return statusFilter === 'all' || (statusFilter === 'review' && review) || (statusFilter === 'ready' && ready) || (statusFilter === 'waiting' && !rows.length);
      }).map(order => <OrderCard key={order.id} integrationId={integrationId} order={order} refresh={refresh} />)}</div>
    </main>
  );
}

export default function MercadoLivrePersonalizacoesPage() {
  const { integration_id: integrationId } = useParams();
  return integrationId ? <AccountOrders integrationId={integrationId} /> : <AccountList />;
}
