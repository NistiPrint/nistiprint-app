import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useSearchParams } from 'react-router-dom';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Eye, Filter, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';

const PAGE_SIZE = 50;
const FILTER_KEYS = ['event_type', 'user_id', 'start_date', 'end_date', 'entity_type', 'entity_id'];

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('pt-BR');
}

function pretty(value) {
  if (value == null || value === '') return '—';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

export default function AuditoriaPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get('page') || 1));
  const filters = useMemo(() => Object.fromEntries(FILTER_KEYS.map((key) => [key, searchParams.get(key) || ''])), [searchParams]);
  const [draft, setDraft] = useState(filters);
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => setDraft(filters), [filters]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams(searchParams);
      params.set('page', String(page));
      params.set('limit', String(PAGE_SIZE));
      const response = await fetch(`/api/v2/auditoria?${params.toString()}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível carregar a auditoria.');
      setEvents(body.events || []);
      setTotal(body.pagination?.total || 0);
    } catch (error) {
      toast.error(error.message || 'Não foi possível carregar a auditoria.');
    } finally { setLoading(false); }
  }, [searchParams, page]);

  useEffect(() => { load(); }, [load]);

  const search = (event) => {
    event.preventDefault();
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      FILTER_KEYS.forEach((key) => {
        const value = draft[key]?.trim();
        if (value) next.set(key, value); else next.delete(key);
      });
      next.set('page', '1');
      return next;
    });
  };

  const clear = () => {
    setDraft(Object.fromEntries(FILTER_KEYS.map((key) => [key, ''])));
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      [...FILTER_KEYS, 'page'].forEach((key) => next.delete(key));
      return next;
    });
  };

  const showDetail = async (eventId) => {
    try {
      const response = await fetch(`/api/v2/auditoria/${eventId}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Evento não encontrado.');
      setSelected(body.event);
    } catch (error) { toast.error(error.message || 'Não foi possível abrir o evento.'); }
  };

  const updatePage = (nextPage) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set('page', String(nextPage));
    return next;
  });
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return <div className="mx-auto max-w-7xl space-y-6 py-4">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-3xl font-semibold">Auditoria</h1><p className="mt-1 text-muted-foreground">Eventos registrados para usuários, setores e dados operacionais.</p></div>
      <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</Button>
    </div>

    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Filter className="h-5 w-5" />Filtros</CardTitle><CardDescription>Os filtros e a paginação permanecem no endereço da página.</CardDescription></CardHeader>
      <CardContent><form onSubmit={search} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div><Label htmlFor="event_type">Evento</Label><Input id="event_type" value={draft.event_type} onChange={(e) => setDraft((v) => ({ ...v, event_type: e.target.value }))} placeholder="Ex.: USUARIO_CRIADO" /></div>
        <div><Label htmlFor="user_id">ID do usuário</Label><Input id="user_id" inputMode="numeric" value={draft.user_id} onChange={(e) => setDraft((v) => ({ ...v, user_id: e.target.value }))} /></div>
        <div><Label htmlFor="entity_type">Entidade</Label><Input id="entity_type" value={draft.entity_type} onChange={(e) => setDraft((v) => ({ ...v, entity_type: e.target.value }))} placeholder="Ex.: usuario ou setor" /></div>
        <div><Label htmlFor="entity_id">ID da entidade</Label><Input id="entity_id" inputMode="numeric" value={draft.entity_id} onChange={(e) => setDraft((v) => ({ ...v, entity_id: e.target.value }))} /></div>
        <div><Label htmlFor="start_date">De</Label><Input id="start_date" type="date" value={draft.start_date} onChange={(e) => setDraft((v) => ({ ...v, start_date: e.target.value }))} /></div>
        <div><Label htmlFor="end_date">Até</Label><Input id="end_date" type="date" value={draft.end_date} onChange={(e) => setDraft((v) => ({ ...v, end_date: e.target.value }))} /></div>
        <div className="flex gap-2 sm:col-span-2 lg:col-span-3"><Button type="submit"><Search className="mr-2 h-4 w-4" />Buscar</Button><Button type="button" variant="outline" onClick={clear}>Limpar</Button></div>
      </form></CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>Eventos ({total})</CardTitle></CardHeader>
      <CardContent>
        <div className="overflow-x-auto"><Table>
          <TableHeader><TableRow><TableHead>Data</TableHead><TableHead>Evento</TableHead><TableHead>Usuário</TableHead><TableHead>Entidade</TableHead><TableHead>Detalhes</TableHead></TableRow></TableHeader>
          <TableBody>
            {events.map((event) => <TableRow key={event.id}>
              <TableCell className="whitespace-nowrap">{formatDate(event.created_at)}</TableCell>
              <TableCell><Badge variant="outline">{event.tipo_evento || '—'}</Badge></TableCell>
              <TableCell>{event.usuario_id ?? 'Sistema'}</TableCell>
              <TableCell>{event.entidade_afetada || '—'}{event.registro_id != null ? ` · ${event.registro_id}` : ''}</TableCell>
              <TableCell><Button size="sm" variant="ghost" onClick={() => showDetail(event.id)}><Eye className="mr-2 h-4 w-4" />Detalhes</Button></TableCell>
            </TableRow>)}
            {!events.length && <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">{loading ? 'Carregando eventos…' : 'Nenhum evento encontrado.'}</TableCell></TableRow>}
          </TableBody>
        </Table></div>
        <div className="mt-4 flex items-center justify-between border-t pt-4"><span className="text-sm text-muted-foreground">Página {page} de {totalPages}</span><div className="flex gap-2"><Button variant="outline" disabled={page <= 1 || loading} onClick={() => updatePage(page - 1)}>Anterior</Button><Button variant="outline" disabled={page >= totalPages || loading} onClick={() => updatePage(page + 1)}>Próxima</Button></div></div>
      </CardContent>
    </Card>

    {selected && <Card className="border-primary/40">
      <CardHeader className="flex flex-row items-start justify-between"><div><CardTitle>{selected.tipo_evento}</CardTitle><CardDescription>{formatDate(selected.created_at)} · usuário {selected.usuario_id ?? 'Sistema'} · {selected.entidade_afetada || 'sem entidade'} {selected.registro_id ?? ''}</CardDescription></div><Button variant="ghost" onClick={() => setSelected(null)}>Fechar</Button></CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2"><div><h3 className="mb-2 text-sm font-semibold">Dados anteriores</h3><pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{pretty(selected.dados_anteriores)}</pre></div><div><h3 className="mb-2 text-sm font-semibold">Dados novos</h3><pre className="max-h-96 overflow-auto rounded bg-muted p-3 text-xs">{pretty(selected.dados_novos)}</pre></div></CardContent>
    </Card>}
  </div>;
}
