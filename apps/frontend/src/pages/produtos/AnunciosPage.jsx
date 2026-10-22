import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import api from '@/services/api';
import ProductSearchInput from '@/components/produtos/ProductSearchInput';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function AnunciosPage() {
  const [data, setData] = useState({ rows: [], page: 1, total: 0 });
  const [filters, setFilters] = useState({ integration_id: '', q: '', status: '' });
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const load = useCallback(async (page = 1) => {
    try {
      const params = { page, per_page: 50 };
      Object.entries(filters).forEach(([key, value]) => { if (value) params[key] = value; });
      const response = await api.get('/anuncios', { params });
      setData(response.data.data);
    } catch (error) { toast.error(error.message || 'Não foi possível carregar anúncios.'); }
  }, [filters]);
  useEffect(() => { load(); }, [load]);
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
    if (!filters.integration_id) return toast.error('Informe o ID da conta integrada para sincronizar.');
    setSyncing(true);
    try {
      await api.post(`/integracoes/${filters.integration_id}/catalogo/sincronizar`);
      toast.success('Sincronização de anúncios enfileirada.');
    } catch (error) { toast.error(error.message || 'Não foi possível enfileirar a sincronização.'); }
    finally { setSyncing(false); }
  };
  return <div className="mx-auto max-w-6xl space-y-5 py-6">
    <header><h1 className="text-2xl font-semibold">Anúncios</h1><p className="text-sm text-muted-foreground">Consulte publicações por conta e revise produtos vinculados.</p></header>
    <Card><CardContent className="grid gap-3 p-4 sm:grid-cols-3">
      <label className="grid gap-1 text-sm">Conta integrada<input className="h-10 rounded-md border bg-background px-3" type="number" min="1" value={filters.integration_id} onChange={e => setFilters({ ...filters, integration_id: e.target.value })} placeholder="Todas" /></label>
      <label className="grid gap-1 text-sm">Título do anúncio<input className="h-10 rounded-md border bg-background px-3" value={filters.q} onChange={e => setFilters({ ...filters, q: e.target.value })} /></label>
      <label className="grid gap-1 text-sm">Situação normalizada<select className="h-10 rounded-md border bg-background px-3" value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">Todas</option><option value="ativo">Ativo</option><option value="pausado">Pausado</option><option value="encerrado">Encerrado</option><option value="desconhecido">Desconhecido</option></select></label>
      <div className="sm:col-span-3 sm:text-right"><Button disabled={syncing || !filters.integration_id} onClick={syncAccount}>{syncing ? 'Enfileirando…' : 'Sincronizar conta'}</Button></div>
    </CardContent></Card>
    {!data.rows.length && <Card><CardContent className="p-8 text-sm text-muted-foreground">Nenhum anúncio encontrado para esses filtros.</CardContent></Card>}
    {data.rows.map(header => <Card key={header.id}>
      <CardHeader className="flex flex-row items-start gap-4">
        {header.imagem_comercial && <img src={header.imagem_comercial} alt="" className="h-16 w-16 rounded object-cover" />}
        <div className="min-w-0"><CardTitle className="text-base">{header.titulo || header.item_externo_id}</CardTitle><p className="text-sm text-muted-foreground">Conta {header.integration_id} · {header.item_externo_id} · {header.situacao_normalizada || 'situação pendente'}</p>{header.url && <a className="text-sm underline" href={header.url} target="_blank" rel="noreferrer">Abrir no marketplace</a>}</div>
      </CardHeader>
      <CardContent className="space-y-3">{(header.unidades || []).map(unit => <div key={unit.id} className="grid gap-2 border-t pt-3 md:grid-cols-[1fr_2fr_auto] md:items-end">
        <p className="text-sm">Variação {unit.variacao_externa_id || 'simples'} · SKU {unit.sku_externo || '—'} · produto {unit.produto_id || 'pendente'}</p>
        <ProductSearchInput value={selected[unit.id]?.name || ''} selectedProductId={selected[unit.id]?.id} onChange={() => setSelected(current => ({ ...current, [unit.id]: null }))} onProductSelect={product => setSelected(current => ({ ...current, [unit.id]: product }))} onlyMarketable placeholder="Buscar produto para vincular" />
        <Button disabled={busy === unit.id || !selected[unit.id]} onClick={() => linkUnit(unit, header)}>{busy === unit.id ? 'Salvando…' : 'Salvar vínculo'}</Button>
        {unit.produto_id && <Link className="text-sm underline md:col-span-3" to={`/produtos/${unit.produto_id}/editar`}>Abrir ficha do produto vinculado</Link>}
      </div>)}</CardContent>
    </Card>)}
    <div className="flex items-center justify-between"><span className="text-sm text-muted-foreground">Página {data.page} · {data.total} anúncios</span><div className="flex gap-2"><Button variant="outline" disabled={data.page <= 1} onClick={() => load(data.page - 1)}>Anterior</Button><Button variant="outline" disabled={data.page * 50 >= data.total} onClick={() => load(data.page + 1)}>Próxima</Button></div></div>
  </div>;
}
