import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Copy,
  Eye,
  RefreshCw,
  RotateCcw,
  Search,
  Webhook
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

const PAGE_SIZE = 50;

const emptyFilters = {
  source: 'bling',
  status: '',
  bling_id: '',
  numero_loja: '',
  pedido_id: '',
  correlation_id: '',
  since: '',
  until: ''
};

function statusBadge(status) {
  const value = status || 'unknown';
  if (value === 'success' || value === 'skipped') {
    return <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200"><CheckCircle2 className="h-3 w-3 mr-1" />{value}</Badge>;
  }
  if (value === 'failed' || value === 'dead_letter') {
    return <Badge variant="destructive"><AlertCircle className="h-3 w-3 mr-1" />{value}</Badge>;
  }
  if (value === 'processing') {
    return <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200"><RefreshCw className="h-3 w-3 mr-1 animate-spin" />processing</Badge>;
  }
  return <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200"><Clock className="h-3 w-3 mr-1" />{value}</Badge>;
}

function formatDate(value) {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString('pt-BR');
  } catch {
    return value;
  }
}

function WebhooksPage() {
  const [events, setEvents] = useState([]);
  const [filters, setFilters] = useState(emptyFilters);
  const [appliedFilters, setAppliedFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [attempts, setAttempts] = useState([]);
  const [logs, setLogs] = useState([]);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), per_page: String(PAGE_SIZE) });
    Object.entries(appliedFilters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    return params.toString();
  }, [appliedFilters, page]);

  const fetchEvents = async () => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/webhooks/events?${queryString}`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Falha ao buscar webhooks');
      }
      setEvents(data.events || []);
      setHasMore(Boolean(data.pagination?.has_more));
    } catch (error) {
      toast.error(error.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchDetails = async (eventId) => {
    setDetailsLoading(true);
    try {
      const [eventResponse, logsResponse] = await Promise.all([
        fetch(`/api/v2/webhooks/events/${eventId}`),
        fetch(`/api/v2/webhooks/events/${eventId}/logs`)
      ]);
      const eventData = await eventResponse.json();
      const logsData = await logsResponse.json();
      if (!eventResponse.ok || !eventData.success) {
        throw new Error(eventData.error || 'Falha ao buscar payload');
      }
      if (!logsResponse.ok || !logsData.success) {
        throw new Error(logsData.error || 'Falha ao buscar logs');
      }
      setSelectedEvent(eventData.event);
      setAttempts(logsData.attempts || []);
      setLogs(logsData.logs || []);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setDetailsLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [queryString]);

  const applyFilters = () => {
    setPage(1);
    setAppliedFilters(filters);
  };

  const clearFilters = () => {
    setFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    setPage(1);
  };

  const reprocessSelected = async () => {
    if (!selectedEvent) return;
    setReprocessing(true);
    try {
      const response = await fetch(`/api/v2/webhooks/events/${selectedEvent.id}/reprocess`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Falha ao reprocessar webhook');
      }
      toast.success('Webhook reenfileirado para processamento.');
      await fetchEvents();
      await fetchDetails(selectedEvent.id);
    } catch (error) {
      toast.error(error.message);
    } finally {
      setReprocessing(false);
    }
  };

  const canReprocess = selectedEvent && ['failed', 'dead_letter'].includes(selectedEvent.last_status);

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Webhook className="h-8 w-8 text-primary" /> Webhooks
          </h1>
          <p className="text-muted-foreground mt-1">
            Payload recebido, tentativas de processamento e reprocessamento manual de falhas.
          </p>
        </div>
        <Button variant="outline" onClick={fetchEvents} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filtros</CardTitle>
          <CardDescription>Use origem, status, pedido interno ou correlation_id.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={filters.source}
              onChange={(event) => setFilters({ ...filters, source: event.target.value })}
            >
              <option value="bling">Bling</option>
              <option value="shopee">Shopee</option>
              <option value="mercadolivre">Mercado Livre</option>
              <option value="all">Todas origens</option>
            </select>
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={filters.status}
              onChange={(event) => setFilters({ ...filters, status: event.target.value })}
            >
              <option value="">Todos status</option>
              <option value="pending">pending</option>
              <option value="processing">processing</option>
              <option value="success">success</option>
              <option value="skipped">skipped</option>
              <option value="skipped_inactive_source">skipped_inactive_source</option>
              <option value="failed">failed</option>
              <option value="dead_letter">dead_letter</option>
            </select>
            <Input placeholder="bling_id" value={filters.bling_id} onChange={(event) => setFilters({ ...filters, bling_id: event.target.value })} />
            <Input placeholder="numero_loja" value={filters.numero_loja} onChange={(event) => setFilters({ ...filters, numero_loja: event.target.value })} />
            <Input placeholder="pedido_id" value={filters.pedido_id} onChange={(event) => setFilters({ ...filters, pedido_id: event.target.value })} />
            <Input placeholder="correlation_id" className="md:col-span-2" value={filters.correlation_id} onChange={(event) => setFilters({ ...filters, correlation_id: event.target.value })} />
            <Input type="datetime-local" value={filters.since} onChange={(event) => setFilters({ ...filters, since: event.target.value })} />
            <Input type="datetime-local" value={filters.until} onChange={(event) => setFilters({ ...filters, until: event.target.value })} />
          </div>
          <div className="flex gap-2 mt-4">
            <Button onClick={applyFilters}><Search className="h-4 w-4 mr-2" /> Filtrar</Button>
            <Button variant="outline" onClick={clearFilters}>Limpar</Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)] gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Eventos Recebidos</CardTitle>
            <CardDescription>{events.length} eventos nesta pagina</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead>Pedido</TableHead>
                    <TableHead>Bling</TableHead>
                    <TableHead>Tentativas</TableHead>
                    <TableHead>Recebido</TableHead>
                    <TableHead className="text-right">Acoes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow><TableCell colSpan={6} className="text-center py-8">Carregando...</TableCell></TableRow>
                  ) : events.length === 0 ? (
                    <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Nenhum webhook encontrado.</TableCell></TableRow>
                  ) : events.map((event) => (
                    <TableRow key={event.id} className={selectedEvent?.id === event.id ? 'bg-muted/50' : ''}>
                      <TableCell>{statusBadge(event.last_status)}</TableCell>
                      <TableCell>
                        <div className="font-medium">{event.pedido_id ? `#${event.pedido_id}` : '-'}</div>
                        <div className="text-xs text-muted-foreground">{event.numero_loja || '-'}</div>
                      </TableCell>
                      <TableCell>
                        <div className="font-mono text-xs">{event.bling_id || '-'}</div>
                        <div className="text-xs text-muted-foreground">{event.source}</div>
                      </TableCell>
                      <TableCell>{event.attempt_count || 0}</TableCell>
                      <TableCell className="text-xs">{formatDate(event.received_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => fetchDetails(event.id)}>
                          <Eye className="h-4 w-4 mr-1" /> Ver
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex justify-between items-center mt-4">
              <Button variant="outline" disabled={page === 1 || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>Anterior</Button>
              <span className="text-sm text-muted-foreground">Pagina {page}</span>
              <Button variant="outline" disabled={!hasMore || loading} onClick={() => setPage((value) => value + 1)}>Proxima</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>Detalhe do Evento</CardTitle>
              <CardDescription>
                {selectedEvent ? `webhook_event #${selectedEvent.id}` : 'Selecione um evento para inspecionar.'}
              </CardDescription>
            </div>
            {selectedEvent && (
              <Button onClick={reprocessSelected} disabled={!canReprocess || reprocessing} size="sm">
                <RotateCcw className={`h-4 w-4 mr-2 ${reprocessing ? 'animate-spin' : ''}`} /> Reprocessar
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {!selectedEvent ? (
              <div className="text-center py-16 text-muted-foreground">Nenhum evento selecionado.</div>
            ) : detailsLoading ? (
              <div className="text-center py-16">Carregando detalhe...</div>
            ) : (
              <Tabs defaultValue="payload">
                <TabsList className="grid grid-cols-3 mb-4">
                  <TabsTrigger value="payload">Payload</TabsTrigger>
                  <TabsTrigger value="attempts">Tentativas</TabsTrigger>
                  <TabsTrigger value="logs">Logs</TabsTrigger>
                </TabsList>

                <TabsContent value="payload">
                  <div className="flex justify-end mb-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        navigator.clipboard.writeText(JSON.stringify(selectedEvent.raw_payload || {}, null, 2));
                        toast.success('Payload copiado.');
                      }}
                    >
                      <Copy className="h-4 w-4 mr-2" /> Copiar
                    </Button>
                  </div>
                  <pre className="text-xs bg-muted p-3 rounded-md overflow-auto max-h-[620px]">
                    {JSON.stringify(selectedEvent.raw_payload || {}, null, 2)}
                  </pre>
                </TabsContent>

                <TabsContent value="attempts">
                  <div className="space-y-3">
                    {attempts.length === 0 ? (
                      <div className="text-sm text-muted-foreground">Nenhuma tentativa registrada.</div>
                    ) : attempts.map((attempt) => (
                      <div key={attempt.id} className="border rounded-md p-3">
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <div className="font-medium">Tentativa {attempt.attempt_number}</div>
                          {statusBadge(attempt.status)}
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                          <div>Inicio: {formatDate(attempt.started_at)}</div>
                          <div>Fim: {formatDate(attempt.finished_at)}</div>
                          <div className="col-span-2 font-mono break-all">CID: {attempt.correlation_id}</div>
                          {attempt.error_message && <div className="col-span-2 text-destructive">{attempt.error_type}: {attempt.error_message}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </TabsContent>

                <TabsContent value="logs">
                  <div className="space-y-3 max-h-[620px] overflow-auto pr-1">
                    {logs.length === 0 ? (
                      <div className="text-sm text-muted-foreground">Nenhum log correlacionado.</div>
                    ) : logs.map((log) => (
                      <div key={log.id} className="border rounded-md p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-medium text-sm">{log.stage || log.source}</div>
                          <Badge variant="outline">{log.status || '-'}</Badge>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{formatDate(log.timestamp)} - {log.source}</div>
                        {log.message && <pre className="text-xs whitespace-pre-wrap mt-2 bg-muted p-2 rounded">{String(log.message).slice(0, 2000)}</pre>}
                      </div>
                    ))}
                  </div>
                </TabsContent>
              </Tabs>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default WebhooksPage;
