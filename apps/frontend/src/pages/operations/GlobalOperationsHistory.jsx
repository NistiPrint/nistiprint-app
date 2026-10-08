import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useSearchParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';

const PAGE_SIZE = 50;
const formatDate = (value) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleString('pt-BR') : '—';

export default function GlobalOperationsHistory() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [draft, setDraft] = useState({ status: searchParams.get('status') || '', categoria: searchParams.get('categoria') || '', owner_user_id: searchParams.get('owner_user_id') || '' });
  const [operations, setOperations] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, limit: PAGE_SIZE, total: 0 });
  const [loading, setLoading] = useState(false);
  const page = Math.max(1, Number(searchParams.get('page') || 1));

  useEffect(() => setDraft({ status: searchParams.get('status') || '', categoria: searchParams.get('categoria') || '', owner_user_id: searchParams.get('owner_user_id') || '' }), [searchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams(searchParams);
      params.set('page', String(page));
      params.set('limit', String(PAGE_SIZE));
      const response = await fetch(`/api/v2/operations/global?${params}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Não foi possível consultar operações.');
      setOperations(body.data || []);
      setPagination(body.pagination || { page, limit: PAGE_SIZE, total: 0 });
    } catch (error) { toast.error(error.message || 'Não foi possível consultar operações.'); }
    finally { setLoading(false); }
  }, [page, searchParams]);

  useEffect(() => { load(); }, [load]);

  const apply = (event) => {
    event.preventDefault();
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const key of ['status', 'categoria', 'owner_user_id']) {
        const value = draft[key].trim();
        if (value) next.set(key, value); else next.delete(key);
      }
      next.set('page', '1');
      return next;
    });
  };
  const totalPages = Math.max(1, Math.ceil((pagination.total || 0) / PAGE_SIZE));

  return <Card className="mt-6">
    <CardHeader className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
      <div><CardTitle>Atividade assíncrona global</CardTitle><CardDescription>Operações persistidas, além dos logs de execução do worker.</CardDescription></div>
      <Button variant="outline" size="sm" onClick={load} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Atualizar</Button>
    </CardHeader>
    <CardContent>
      <form onSubmit={apply} className="mb-4 grid gap-2 sm:grid-cols-4">
        <select aria-label="Status" className="h-10 rounded-md border bg-background px-3 text-sm" value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))}>
          <option value="">Todos os status</option><option value="AGUARDANDO">Aguardando</option><option value="EM_ANDAMENTO">Em andamento</option><option value="CONCLUIDO">Concluído</option><option value="ERRO">Falhou</option>
        </select>
        <Input aria-label="Categoria" placeholder="Categoria" value={draft.categoria} onChange={(event) => setDraft((current) => ({ ...current, categoria: event.target.value }))} />
        <Input aria-label="ID do usuário" inputMode="numeric" placeholder="ID do usuário" value={draft.owner_user_id} onChange={(event) => setDraft((current) => ({ ...current, owner_user_id: event.target.value }))} />
        <Button type="submit"><Search className="mr-2 h-4 w-4" />Filtrar</Button>
      </form>
      <div className="overflow-x-auto"><Table>
        <TableHeader><TableRow><TableHead>Operação</TableHead><TableHead>Status</TableHead><TableHead>Responsável</TableHead><TableHead>Última atualização</TableHead><TableHead>Resultado</TableHead></TableRow></TableHeader>
        <TableBody>
          {operations.map((operation) => {
            const failedCount = Number(operation.dados_adicionais?.falha || operation.dados_adicionais?.falhas || operation.dados_adicionais?.erro || 0);
            const failed = operation.status === 'ERRO' || failedCount > 0;
            return <TableRow key={operation.id}>
              <TableCell><strong>{operation.titulo || operation.categoria}</strong><span className="block text-xs text-muted-foreground">{operation.mensagem || operation.etapa || '—'}</span></TableCell>
              <TableCell><Badge variant={failed ? 'destructive' : 'outline'}>{failed && operation.status === 'CONCLUIDO' ? 'Concluído com falhas' : operation.status}</Badge></TableCell>
              <TableCell>{operation.owner_user_id}</TableCell>
              <TableCell className="whitespace-nowrap">{formatDate(operation.updated_at)}</TableCell>
              <TableCell>{operation.dados_adicionais?.sucesso != null || operation.dados_adicionais?.falha != null || operation.dados_adicionais?.falhas != null ? `${operation.dados_adicionais.sucesso || 0} sucesso(s) · ${failedCount} erro(s)` : operation.erro_resumo || '—'}</TableCell>
            </TableRow>;
          })}
          {!operations.length && <TableRow><TableCell colSpan={5} className="py-8 text-center text-muted-foreground">{loading ? 'Carregando…' : 'Nenhuma operação encontrada.'}</TableCell></TableRow>}
        </TableBody>
      </Table></div>
      <div className="mt-4 flex items-center justify-between border-t pt-4"><span className="text-sm text-muted-foreground">{pagination.total || 0} operações · página {page} de {totalPages}</span><div className="flex gap-2"><Button variant="outline" disabled={page <= 1 || loading} onClick={() => setSearchParams((current) => { const next = new URLSearchParams(current); next.set('page', String(page - 1)); return next; })}>Anterior</Button><Button variant="outline" disabled={page >= totalPages || loading} onClick={() => setSearchParams((current) => { const next = new URLSearchParams(current); next.set('page', String(page + 1)); return next; })}>Próxima</Button></div></div>
    </CardContent>
  </Card>;
}
