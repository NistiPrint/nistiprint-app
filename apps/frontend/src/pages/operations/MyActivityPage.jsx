import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useSearchParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { CheckCheck, CircleAlert, ExternalLink, RefreshCw } from 'lucide-react';

const PAGE_SIZE = 50;

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('pt-BR');
}

function statusLabel(status) {
  return ({
    AGUARDANDO: 'Na fila', EM_ANDAMENTO: 'Em andamento', CONCLUIDO: 'Concluído',
    ERRO: 'Falhou', FAILED: 'Concluído com falhas', CANCELADO: 'Cancelado',
  })[status] || status || 'Atualizando';
}

export default function MyActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get('pagina') || 1));
  const tab = searchParams.get('tipo') === 'avisos' ? 'avisos' : 'processos';
  const operationId = searchParams.get('operation_id');
  const [data, setData] = useState({ operations: [], notifications: [], unread_count: 0, pagination: {} });
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async ({ silent = false } = {}) => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/notifications/center?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`);
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao carregar atividade.');
      setData(body.data);
      setLoadError(false);
    } catch (error) {
      setLoadError(true);
      if (!silent) toast.error(error.message || 'Não foi possível carregar sua atividade.');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    load();
    const refreshTimer = window.setInterval(() => load({ silent: true }), 30000);
    return () => window.clearInterval(refreshTimer);
  }, [load]);

  const selectTab = (value) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('tipo', value);
      next.delete('pagina');
      return next;
    });
  };

  const openOperation = useCallback((id) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('operation_id', String(id));
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  useEffect(() => {
    if (!operationId) {
      setSelected(null);
      return undefined;
    }
    let cancelled = false;
    setSelected(null);
    const loadOperation = async () => {
      try {
        const response = await fetch(`/api/v2/notifications/operations/${encodeURIComponent(operationId)}`);
        const body = await response.json();
        if (!response.ok || !body.success) throw new Error(body.error || 'Processo não encontrado.');
        if (!cancelled) setSelected(body.data);
      } catch (error) {
        if (!cancelled) toast.error(error.message || 'Não foi possível abrir o processo.');
      }
    };
    loadOperation();
    return () => { cancelled = true; };
  }, [operationId]);

  const closeOperation = () => {
    setSelected(null);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete('operation_id');
      return next;
    }, { replace: true });
  };

  const markRead = async (notification) => {
    if (notification.lida || notification.read_at) return;
    try {
      const response = await fetch(`/api/v2/notifications/${notification.id}/read`, { method: 'PATCH' });
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.error || 'Falha ao atualizar aviso.');
      setData((current) => ({
        ...current,
        unread_count: Math.max(0, current.unread_count - 1),
        notifications: current.notifications.map((item) => item.id === notification.id ? { ...item, lida: true } : item),
      }));
    } catch (error) { toast.error(error.message || 'Não foi possível marcar como lido.'); }
  };

  const totals = data.pagination || {};
  const totalPages = Math.max(1, Math.ceil(Math.max(totals.operations_total || 0, totals.notifications_total || 0) / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-6xl space-y-6 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">Minha atividade</h1>
          <p className="mt-1 text-muted-foreground">Acompanhe seus processos, resultados e avisos.</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Atualizar
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card><CardHeader className="pb-2"><CardDescription>Em andamento</CardDescription><CardTitle>{data.operations.filter((item) => ['AGUARDANDO', 'EM_ANDAMENTO'].includes(item.status)).length}</CardTitle></CardHeader></Card>
        <Card><CardHeader className="pb-2"><CardDescription>Avisos não lidos</CardDescription><CardTitle>{data.unread_count || 0}</CardTitle></CardHeader></Card>
        <Card><CardHeader className="pb-2"><CardDescription>Processos recentes</CardDescription><CardTitle>{totals.operations_total || 0}</CardTitle></CardHeader></Card>
      </div>

      {loadError && <div role="status" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">A conexão está indisponível. O histórico será atualizado quando o serviço voltar.</div>}

      <Tabs value={tab} onValueChange={selectTab}>
        <TabsList>
          <TabsTrigger value="processos">Processos</TabsTrigger>
          <TabsTrigger value="avisos">Avisos{data.unread_count ? ` (${data.unread_count})` : ''}</TabsTrigger>
        </TabsList>
        <TabsContent value="processos" className="mt-4 space-y-3">
          {loading && !data.operations.length ? <p className="py-10 text-center text-muted-foreground">Carregando processos…</p> : null}
          {!loading && !data.operations.length ? <Card><CardContent className="py-12 text-center text-muted-foreground">Você ainda não tem processos recentes.</CardContent></Card> : null}
          {data.operations.map((operation) => {
            const counts = operation.dados_adicionais || {};
            const failedCount = Number(counts.falha || counts.falhas || counts.erro || 0);
            const failed = operation.status === 'ERRO' || failedCount > 0;
            const progress = operation.progresso_total > 0
              ? Math.round((Number(operation.progresso_atual || 0) / Number(operation.progresso_total)) * 100)
              : null;
            return <Card key={operation.id}>
              <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <button className="min-w-0 text-left" onClick={() => openOperation(operation.id)}>
                  <span className="flex flex-wrap items-center gap-2 font-medium">
                    {operation.titulo || operation.nome || operation.categoria || 'Processo'}
                    <Badge variant={failed ? 'destructive' : 'outline'}>{failed && operation.status === 'CONCLUIDO' ? 'Concluído com falhas' : statusLabel(operation.status)}</Badge>
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">Iniciado {formatDate(operation.created_at)}{operation.updated_at ? ` · Atualizado ${formatDate(operation.updated_at)}` : ''}</span>
                  {operation.mensagem && <span className="mt-1 block text-sm">{operation.mensagem}</span>}
                  {(counts.sucesso != null || counts.falha != null || counts.falhas != null || counts.erro != null) && <span className="mt-1 block text-xs text-muted-foreground">{counts.sucesso || 0} sucesso(s) · {failedCount} erro(s)</span>}
                  {progress != null && <span className="mt-2 block h-1.5 overflow-hidden rounded bg-muted"><span className="block h-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></span>}
                </button>
                <Button variant="outline" size="sm" onClick={() => openOperation(operation.id)}>Detalhes</Button>
              </CardContent>
            </Card>;
          })}
        </TabsContent>
        <TabsContent value="avisos" className="mt-4 space-y-3">
          {!data.notifications.length && !loading ? <Card><CardContent className="py-12 text-center text-muted-foreground">Nenhum aviso no período.</CardContent></Card> : null}
          {data.notifications.map((notification) => {
            const read = notification.lida || !!notification.read_at;
            const route = notification.dados_adicionais?.rota_destino;
            return <Card key={notification.id} className={read ? '' : 'border-primary/30 bg-primary/[0.03]'}>
              <CardContent className="flex items-start gap-3 p-4">
                {notification.tipo === 'erro' ? <CircleAlert className="mt-1 h-4 w-4 shrink-0 text-destructive" /> : <CheckCheck className="mt-1 h-4 w-4 shrink-0 text-primary" />}
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-base">{notification.titulo || notification.event_type || 'Aviso'}</CardTitle>
                  <CardDescription className="mt-1 whitespace-pre-wrap">{notification.mensagem}</CardDescription>
                  <p className="mt-2 text-xs text-muted-foreground">{formatDate(notification.created_at || notification.data_envio)}</p>
                  <div className="mt-2 flex gap-2">
                    {notification.operacao_id && <Button size="sm" variant="outline" onClick={() => openOperation(notification.operacao_id)}>Ver processo</Button>}
                    {route && <Button size="sm" variant="link" asChild><a href={route}><ExternalLink className="mr-1 h-3 w-3" />Abrir item</a></Button>}
                  </div>
                </div>
                {!read && <Button size="sm" variant="ghost" onClick={() => markRead(notification)}>Marcar como lido</Button>}
              </CardContent>
            </Card>;
          })}
        </TabsContent>
      </Tabs>

      {selected && <Card className="border-primary/40">
        <CardHeader className="flex flex-row items-start justify-between">
          <div><CardTitle>Detalhes do processo</CardTitle><CardDescription>{selected.titulo || selected.categoria || selected.id}</CardDescription></div>
          <Button variant="ghost" size="sm" onClick={closeOperation}>Fechar</Button>
        </CardHeader>
        <CardContent>
          <div className="mb-3 flex flex-wrap gap-3 text-sm"><Badge variant={selected.status === 'ERRO' || Number(selected.dados_adicionais?.falha || selected.dados_adicionais?.falhas || selected.dados_adicionais?.erro || 0) > 0 ? 'destructive' : 'outline'}>{selected.status === 'CONCLUIDO' && Number(selected.dados_adicionais?.falha || selected.dados_adicionais?.falhas || selected.dados_adicionais?.erro || 0) > 0 ? 'Concluído com falhas' : statusLabel(selected.status)}</Badge><span>Iniciado {formatDate(selected.created_at)}</span>{selected.finalizado_em && <span>Finalizado {formatDate(selected.finalizado_em)}</span>}</div>
          {selected.mensagem && <p className="mb-3 text-sm">{selected.mensagem}</p>}
          {selected.erro_resumo && <p className="mb-3 rounded border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{selected.erro_resumo}</p>}
          {selected.dados_adicionais && <pre className="overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(selected.dados_adicionais, null, 2)}</pre>}
        </CardContent>
      </Card>}

      <div className="flex items-center justify-between border-t pt-4">
        <span className="text-sm text-muted-foreground">Página {page} de {totalPages}</span>
        <div className="flex gap-2">
          <Button variant="outline" disabled={page <= 1 || loading} onClick={() => setSearchParams((current) => { const next = new URLSearchParams(current); next.set('pagina', String(page - 1)); return next; })}>Anterior</Button>
          <Button variant="outline" disabled={page >= totalPages || loading} onClick={() => setSearchParams((current) => { const next = new URLSearchParams(current); next.set('pagina', String(page + 1)); return next; })}>Próxima</Button>
        </div>
      </div>
    </div>
  );
}
