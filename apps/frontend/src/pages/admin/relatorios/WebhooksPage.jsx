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
  source: 'all',
  status: '',
  bling_id: '',
  numero_loja: '',
  pedido_id: '',
  correlation_id: '',
  since: '',
  until: ''
};

function nextActionForEvent(event) {
  const diagnostic = `${event?.last_error_type || ''} ${event?.last_error_message || ''} ${event?.signature_status || ''}`.toLowerCase();
  if (diagnostic.includes('signature') || diagnostic.includes('assinatura')) return 'Conferir a assinatura e o envelope recebido no n8n.';
  if (diagnostic.includes('token') || diagnostic.includes('oauth') || diagnostic.includes('credential')) return 'Regularizar a credencial da conta e reprocessar o mesmo evento.';
  if (diagnostic.includes('account') || diagnostic.includes('conta') || diagnostic.includes('integration')) return 'Resolver o vínculo da conta de integração antes de reprocessar.';
  if (diagnostic.includes('sku') || diagnostic.includes('produto') || diagnostic.includes('mapping')) return 'Vincular o anúncio ao produto interno; não inferir baixa de estoque.';
  if (event?.last_status === 'processing') return 'Aguardar o lease ou verificar se o worker deixou uma execução interrompida.';
  return 'Corrigir a causa registrada e reprocessar preservando este evento.';
}

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
  const [reprocessError, setReprocessError] = useState('');
  const [showUnmappedListings, setShowUnmappedListings] = useState(false);
  const [unmappedListings, setUnmappedListings] = useState([]);
  const [unmappedPage, setUnmappedPage] = useState(1);
  const [unmappedHasMore, setUnmappedHasMore] = useState(false);
  const [unmappedLoading, setUnmappedLoading] = useState(false);

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

  const fetchUnmappedListings = async () => {
    setUnmappedLoading(true);
    try {
      const response = await fetch(`/api/v2/webhooks/exceptions/unmapped-listings?page=${unmappedPage}&per_page=${PAGE_SIZE}`);
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Falha ao buscar anúncios sem vínculo');
      setUnmappedListings(data.exceptions || []);
      setUnmappedHasMore(Boolean(data.pagination?.has_more));
    } catch (error) {
      toast.error(error.message);
    } finally {
      setUnmappedLoading(false);
    }
  };

  const fetchDetails = async (eventId) => {
    setDetailsLoading(true);
    setReprocessError('');
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

  useEffect(() => {
    if (showUnmappedListings) fetchUnmappedListings();
  }, [showUnmappedListings, unmappedPage]);

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
    setReprocessError('');
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
      setReprocessError(error.message);
      toast.error(error.message);
    } finally {
      setReprocessing(false);
    }
  };

  const canReprocess = selectedEvent
    && ['failed', 'failed_terminal', 'dead_letter', 'manual_intervention', 'pending_retry'].includes(selectedEvent.last_status)
    && selectedEvent.raw_payload && !selectedEvent.raw_payload._purgado_retencao;

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
        <Button variant="outline" onClick={() => setShowUnmappedListings((shown) => !shown)}>
          {showUnmappedListings ? 'Ocultar exceções de SKU' : 'Ver anúncios sem vínculo'}
        </Button>
      </div>

      {showUnmappedListings && (
        <Card>
          <CardHeader>
            <CardTitle>Anúncios sem produto interno</CardTitle>
            <CardDescription>Revisar cada vínculo por conta e variação antes de habilitar qualquer regra de estoque. Esta lista não altera mapeamentos.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border overflow-hidden">
              <Table>
                <TableHeader><TableRow><TableHead>Conta</TableHead><TableHead>Anúncio</TableHead><TableHead>Variação</TableHead><TableHead>SKU</TableHead><TableHead>Candidato interno</TableHead><TableHead>Último erro</TableHead></TableRow></TableHeader>
                <TableBody>
                  {unmappedLoading ? <TableRow><TableCell colSpan={6} className="text-center py-6">Carregando...</TableCell></TableRow> : unmappedListings.length === 0 ? <TableRow><TableCell colSpan={6} className="text-center py-6 text-muted-foreground">Nenhum anúncio sem vínculo nesta página.</TableCell></TableRow> : unmappedListings.map((listing) => (
                    <TableRow key={listing.id}>
                      <TableCell><div>{listing.integration?.instance_name || listing.integration?.description || 'Conta não vinculada'}</div><div className="text-xs text-muted-foreground">{listing.integration?.platform_slug || listing.integration?.module_id || '-'} · #{listing.integration_id ?? '?'}</div></TableCell>
                      <TableCell><div className="font-mono text-xs">{listing.item_externo_id || '-'}</div><div className="text-xs text-muted-foreground">{listing.titulo || listing.status || '-'}</div></TableCell>
                      <TableCell className="font-mono text-xs">{listing.variacao_externa_id || '-'}</TableCell>
                      <TableCell>{listing.sku_anuncio || '-'}</TableCell>
                      <TableCell className="text-xs">{listing.sku_candidate_status === 'UNICO' ? <><strong>Revisar:</strong> {listing.sku_candidates?.[0]?.nome} (#{listing.sku_candidates?.[0]?.id})</> : listing.sku_candidate_status === 'AMBIGUO' ? `${listing.sku_candidates?.length || 0} candidatos; revisar manualmente` : 'Sem SKU interno exato'}</TableCell>
                      <TableCell className="text-xs text-destructive">{listing.ultimo_erro || 'Mapeamento interno ausente'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex justify-between items-center mt-4">
              <Button variant="outline" disabled={unmappedPage === 1 || unmappedLoading} onClick={() => setUnmappedPage((value) => Math.max(1, value - 1))}>Anterior</Button>
              <span className="text-sm text-muted-foreground">Página {unmappedPage}</span>
              <Button variant="outline" disabled={!unmappedHasMore || unmappedLoading} onClick={() => setUnmappedPage((value) => value + 1)}>Próxima</Button>
            </div>
          </CardContent>
        </Card>
      )}

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
              <option value="pending_retry">pending_retry</option>
              <option value="manual_intervention">manual_intervention</option>
              <option value="failed_terminal">failed_terminal</option>
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
                    <TableHead>Canal / conta</TableHead>
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
                        <div className="font-mono text-xs">{event.provider_topic || event.bling_id || '-'}</div>
                        <div className="text-xs text-muted-foreground">{event.source} · conta #{event.marketplace_integration_id || event.company_id || '-'}</div>
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
            {reprocessError && <p role="alert" className="mb-4 text-sm text-destructive">{reprocessError}</p>}
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
            {selectedEvent && !detailsLoading && (
              <div className="mt-4 rounded-md border p-3 text-sm space-y-2">
                <div><strong>Recurso:</strong> {selectedEvent.provider_resource || selectedEvent.provider_resource_id || selectedEvent.resolved_order_id || '-'}</div>
                <div><strong>Causa:</strong> {selectedEvent.last_error_type || selectedEvent.signature_error || selectedEvent.resolution_status || 'Nenhuma causa registrada.'} {selectedEvent.last_error_message || ''}</div>
                <div><strong>Próxima ação:</strong> {nextActionForEvent(selectedEvent)}</div>
                <div><strong>Próxima tentativa:</strong> {formatDate(selectedEvent.next_attempt_after)}</div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default WebhooksPage;
