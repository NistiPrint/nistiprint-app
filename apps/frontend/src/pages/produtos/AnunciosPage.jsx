import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, RefreshCw, Store } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import api from '@/services/api';
import ProductSearchInput from '@/components/produtos/ProductSearchInput';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const statusLabels = {
  ativo: 'Ativo', pausado: 'Pausado', encerrado: 'Encerrado',
  em_revisao: 'Em revisão', desconhecido: 'Situação desconhecida',
};
const statusTones = {
  ativo: 'bg-emerald-100 text-emerald-800', pausado: 'bg-amber-100 text-amber-800',
  encerrado: 'bg-slate-100 text-slate-700', em_revisao: 'bg-blue-100 text-blue-800',
  desconhecido: 'bg-slate-100 text-slate-700',
};

const money = value => {
  if (value === null || value === undefined || value === '') return 'Não informado';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) : 'Não informado';
};

const dateTime = value => value ? new Date(value).toLocaleString('pt-BR') : null;

function SyncState({ sync }) {
  if (!sync || sync.status === 'never') return <span className="text-xs text-muted-foreground">Ainda não sincronizada</span>;
  const labels = { running: 'Sincronização em andamento', complete: 'Última sincronização concluída', failed: 'Última sincronização falhou', unavailable: 'Integração indisponível', idle: 'Aguardando sincronização' };
  return <span className="text-xs text-muted-foreground">
    {labels[sync.status] || sync.status}{sync.last_complete_at ? ` · ${dateTime(sync.last_complete_at)}` : ''}{sync.error_code ? ` · ${sync.error_code}` : ''}
  </span>;
}

export default function AnunciosPage() {
  const [data, setData] = useState({ rows: [], page: 1, total: 0, accounts: [] });
  const [filters, setFilters] = useState({ integration_id: '', q: '', status: '' });
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const load = useCallback(async (page = 1) => {
    try {
      const params = { page, per_page: 50 };
      Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value; });
      const response = await api.get('/anuncios', { params });
      const payload = response.data?.data || {};
      setData({
        rows: Array.isArray(payload.rows) ? payload.rows : [],
        page: Number(payload.page) || page,
        total: Number(payload.total) || 0,
        accounts: Array.isArray(payload.accounts) ? payload.accounts : [],
      });
    } catch (error) { toast.error(error.message || 'Não foi possível carregar anúncios.'); }
  }, [filters]);
  useEffect(() => { load(); }, [load]);

  const accounts = Array.isArray(data.accounts) ? data.accounts : [];
  const selectedAccount = useMemo(() => accounts.find(account => String(account.id) === filters.integration_id), [accounts, filters.integration_id]);
  const linkedOnPage = data.rows.reduce((total, header) => total + (header.unidades || []).filter(unit => unit.produto_id).length, 0);
  const unitsOnPage = data.rows.reduce((total, header) => total + (header.unidades || []).length, 0);

  const linkUnit = async (unit, header) => {
    const product = selected[unit.id];
    if (!product) return toast.error('Selecione um produto.');
    setBusy(unit.id);
    try {
      await api.put(`/anuncios/unidades/${unit.id}/vinculo`, {
        integration_id: header.integration_id, produto_id: product.id,
        expected_version: unit.vinculo_versao || 1, motivo: 'Reconciliação manual na central de anúncios',
      });
      toast.success('Vínculo atualizado e auditado.');
      await load(data.page);
    } catch (error) { toast.error(error.message || 'Não foi possível atualizar o vínculo.'); }
    finally { setBusy(null); }
  };

  const syncAccount = async () => {
    if (!filters.integration_id) return toast.error('Selecione uma conta integrada.');
    setSyncing(true);
    try {
      await api.post(`/integracoes/${filters.integration_id}/catalogo/sincronizar`);
      toast.success('Sincronização enfileirada. Os dados aparecem aqui quando o worker terminar.');
      window.setTimeout(() => load(data.page), 5000);
    } catch (error) { toast.error(error.message || 'Não foi possível enfileirar a sincronização.'); }
    finally { setSyncing(false); }
  };

  return <div className="mx-auto max-w-6xl space-y-5 py-6">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-semibold">Anúncios</h1><p className="text-sm text-muted-foreground">Publicações do marketplace, dados comerciais e vínculo com o catálogo interno.</p></div>
      <div className="text-right text-sm text-muted-foreground">{data.total} anúncios · {linkedOnPage}/{unitsOnPage} unidades vinculadas nesta página</div>
    </header>

    <Card><CardContent className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-[1.3fr_1.3fr_1fr_auto_auto] lg:items-end">
      <label className="grid gap-1 text-sm">{accounts.length ? 'Conta do marketplace' : 'ID da conta integrada'}
        {accounts.length ? <select className="h-10 rounded-md border bg-background px-3" value={filters.integration_id} onChange={e => setFilters({ ...filters, integration_id: e.target.value })}>
          <option value="">Todas as contas</option>
          {accounts.map(account => <option key={account.id} value={account.id}>{account.name} · conta {account.id}</option>)}
        </select> : <input className="h-10 rounded-md border bg-background px-3" type="number" min="1" value={filters.integration_id} onChange={e => setFilters({ ...filters, integration_id: e.target.value })} placeholder="Ex.: 6" />}
      </label>
      <label className="grid gap-1 text-sm">Título do anúncio
        <input className="h-10 rounded-md border bg-background px-3" value={filters.q} onChange={e => setFilters({ ...filters, q: e.target.value })} placeholder="Buscar pelo título" />
      </label>
      <label className="grid gap-1 text-sm">Situação
        <select className="h-10 rounded-md border bg-background px-3" value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}>
          <option value="">Todas</option><option value="ativo">Ativo</option><option value="pausado">Pausado</option><option value="encerrado">Encerrado</option><option value="desconhecido">Desconhecido</option>
        </select>
      </label>
      <Button variant="outline" onClick={() => load(data.page)}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
      <Button disabled={syncing || !filters.integration_id} onClick={syncAccount}>{syncing ? 'Enfileirando…' : 'Sincronizar conta'}</Button>
      {selectedAccount && <div className="flex items-center gap-2 text-sm text-muted-foreground sm:col-span-2 lg:col-span-5"><Store className="h-4 w-4" /><span>{selectedAccount.name}</span><span>·</span><SyncState sync={selectedAccount.sync} /></div>}
    </CardContent></Card>

    {!data.rows.length && <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Nenhum anúncio encontrado. Se esta conta ainda não foi importada, selecione-a e sincronize.</CardContent></Card>}
    {data.rows.map(header => <Card key={header.id}>
      <CardHeader className="flex flex-row items-start gap-4 pb-3">
        {header.imagem_comercial ? <img src={header.imagem_comercial} alt="" className="h-20 w-20 shrink-0 rounded-md border object-cover" /> : <div className="grid h-20 w-20 shrink-0 place-items-center rounded-md border bg-muted text-muted-foreground"><Store className="h-7 w-7" /></div>}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <CardTitle className="text-base">{header.titulo || 'Título ainda não sincronizado'}</CardTitle>
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusTones[header.situacao_normalizada] || 'bg-amber-100 text-amber-800'}`}>
              {statusLabels[header.situacao_normalizada] || (header.situacao_normalizada ? header.situacao_normalizada : 'Dados pendentes')}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{header.conta_nome || `Conta ${header.integration_id}`} · ID do anúncio {header.item_externo_id}</p>
          {header.url ? <a className="mt-2 inline-flex items-center gap-1 text-sm underline" href={header.url} target="_blank" rel="noreferrer">Abrir no marketplace <ExternalLink className="h-3.5 w-3.5" /></a> : <p className="mt-2 text-xs text-amber-700">Sem endereço ou detalhes do anúncio. Sincronize a conta para atualizar este registro.</p>}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {(header.unidades || []).map(unit => <div key={unit.id} className="grid gap-3 border-t pt-3 md:grid-cols-[1fr_1.4fr_auto] md:items-end">
          <div className="space-y-1 text-sm">
            <p className="font-medium">{Object.entries(unit.atributos_variacao || {}).map(([name, value]) => `${name}: ${value}`).join(' · ') || (unit.variacao_externa_id ? 'Variação sem atributos descritivos' : 'Anúncio sem variações')}</p>
            {unit.variacao_externa_id && <p className="text-xs text-muted-foreground">ID da variação: {unit.variacao_externa_id}</p>}
            <p className="text-muted-foreground">SKU do marketplace: {unit.sku_externo || 'não informado pelo anúncio'}</p>
            <p className="text-muted-foreground">Preço: {money(unit.preco_observado)} · Disponibilidade: {unit.disponibilidade_observada || 'não informada'}</p>
            {unit.produto_id ? <p>Produto vinculado: <Link className="font-medium underline" to={`/produtos/${unit.produto_id}/editar`}>{unit.produto?.nome || `Produto ${unit.produto_id}`}{unit.produto?.sku ? ` · SKU ${unit.produto.sku}` : ''}</Link><span className="ml-1 text-xs text-muted-foreground">#{unit.produto_id}</span></p> : <p className="font-medium text-amber-700">Vínculo de produto pendente</p>}
          </div>
          <ProductSearchInput value={selected[unit.id]?.name || ''} selectedProductId={selected[unit.id]?.id} onChange={() => setSelected(current => ({ ...current, [unit.id]: null }))} onProductSelect={product => setSelected(current => ({ ...current, [unit.id]: product }))} onlyMarketable placeholder="Buscar produto pelo nome ou SKU" />
          <Button disabled={busy === unit.id || !selected[unit.id]} onClick={() => linkUnit(unit, header)}>{busy === unit.id ? 'Salvando…' : 'Salvar vínculo'}</Button>
        </div>)}
        {!header.unidades?.length && <p className="text-sm text-amber-700">Este anúncio ainda não possui unidades sincronizadas.</p>}
      </CardContent>
    </Card>)}
    <div className="flex items-center justify-between"><span className="text-sm text-muted-foreground">Página {data.page} · {data.total} anúncios</span><div className="flex gap-2"><Button variant="outline" disabled={data.page <= 1} onClick={() => load(data.page - 1)}>Anterior</Button><Button variant="outline" disabled={data.page * 50 >= data.total} onClick={() => load(data.page + 1)}>Próxima</Button></div></div>
  </div>;
}
