import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { batchFromOperation, batchStage, firstPassPercent, isBatchActive, mergeBatchSnapshots } from '@/lib/mercadolivreBatchProgress';

const timeLabel = value => value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' }) : '—';
const itemLabel = item => ({ PENDING: 'Na fila', RUNNING: item.phase === 'RETRY' ? 'Retentando' : 'Processando',
  RETRY_PENDING: item.retry_kind === 'PERSISTENCE' ? 'Aguardando gravação' : 'Aguardando retentativa',
  COMPLETED: 'Concluído', FAILED: 'Falha definitiva' })[item.status] || item.status;

export default function MercadoLivreBatchPanel({ integrationId, focusBatchId, refreshKey, onRefreshOrders, onReprocess, onSnapshot }) {
  const [batches, setBatches] = useState([]);
  const [selectedId, setSelectedId] = useState(focusBatchId || null);
  const [expanded, setExpanded] = useState(Boolean(focusBatchId));
  const [details, setDetails] = useState(null);
  const [error, setError] = useState('');
  const [now, setNow] = useState(Date.now());
  const stateRef = useRef([]);
  const disposed = useRef(false);
  const stream = useRef(false);
  const inFlight = useRef(new Set());
  const controllers = useRef(new Set());
  const refreshTimer = useRef(null);
  const selectedRef = useRef(selectedId);
  const expandedRef = useRef(expanded);
  const lastDetailsRead = useRef(0);
  const callbacks = useRef({ onRefreshOrders, onReprocess, onSnapshot });
  callbacks.current = { onRefreshOrders, onReprocess, onSnapshot };
  selectedRef.current = selectedId;
  expandedRef.current = expanded;

  const request = useCallback(async (suffix) => {
    if (inFlight.current.has(suffix)) return null;
    inFlight.current.add(suffix);
    const controller = new AbortController();
    controllers.current.add(controller);
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`/api/v2/mercadolivre/integracoes/${integrationId}/personalizados/${suffix}`, {
        credentials: 'same-origin', signal: controller.signal,
      });
      const body = await response.json();
      if (!response.ok || !body.success) throw new Error(body.message || 'Falha ao consultar o lote.');
      return body.data;
    } finally {
      window.clearTimeout(timeout);
      controllers.current.delete(controller);
      inFlight.current.delete(suffix);
    }
  }, [integrationId]);

  const applySnapshots = useCallback((incoming, fromStream = false) => {
    if (disposed.current) return;
    for (const batch of incoming) {
      const previous = stateRef.current.find(item => String(item.id) === String(batch.id));
      if (previous && (Number(batch.success_count || 0) > Number(previous.success_count || 0)
          || (isBatchActive(previous) && !isBatchActive(batch) && !fromStream))) {
        if (refreshTimer.current == null && callbacks.current.onRefreshOrders) {
          refreshTimer.current = window.setTimeout(() => {
            refreshTimer.current = null;
            callbacks.current.onRefreshOrders?.();
          }, isBatchActive(batch) ? 3000 : 0);
        }
      }
    }
    const next = mergeBatchSnapshots(stateRef.current, incoming);
    stateRef.current = next;
    setBatches(next);
    setSelectedId(current => current || focusBatchId || next[0]?.id || null);
    const selected = next.find(batch => String(batch.id) === String(selectedRef.current || focusBatchId || next[0]?.id));
    if (selected) callbacks.current.onSnapshot?.(selected);
    setError('');
  }, [focusBatchId]);

  const readDetails = useCallback(async (batchId, force = false) => {
    if (!batchId || (!force && Date.now() - lastDetailsRead.current < 2000)) return;
    lastDetailsRead.current = Date.now();
    const result = await request(`lotes/${encodeURIComponent(batchId)}`);
    if (result && !disposed.current && String(selectedRef.current) === String(batchId)) {
      setDetails(result);
      applySnapshots([result]);
    }
  }, [request, applySnapshots]);

  const readSummaries = useCallback(async () => {
    try {
      const result = await request(focusBatchId
        ? `lotes/${encodeURIComponent(focusBatchId)}?include_items=false` : 'lotes?limit=5');
      if (result) applySnapshots(focusBatchId ? [result] : result.batches || []);
      if (expandedRef.current) await readDetails(selectedRef.current);
    } catch (err) {
      if (!disposed.current) setError(err.name === 'AbortError' ? 'A consulta demorou. Tentando atualizar o progresso…' : err.message);
    }
  }, [request, focusBatchId, applySnapshots, readDetails]);

  useEffect(() => {
    disposed.current = false;
    stateRef.current = [];
    setBatches([]);
    setDetails(null);
    setSelectedId(focusBatchId || null);
    readSummaries();
    const onProgress = event => {
      if (String(event.detail?.integrationId) !== String(integrationId)) return;
      const batch = batchFromOperation(event.detail.operation);
      if (focusBatchId && String(batch.id) !== String(focusBatchId)) return;
      applySnapshots([batch], true);
      if (expandedRef.current) readDetails(selectedRef.current).catch(err => { if (!disposed.current) setError(err.message); });
    };
    const onStream = event => {
      stream.current = Boolean(event.detail?.connected);
      if (stream.current) readSummaries();
    };
    window.addEventListener('activity:mercadolivre-progress', onProgress);
    window.addEventListener('activity:stream-state', onStream);
    window.dispatchEvent(new CustomEvent('activity:stream-query'));
    const poll = window.setInterval(() => {
      const active = stateRef.current.filter(isBatchActive);
      if (!stream.current || active.some(batch => !batch.created_by)) readSummaries();
    }, 2000);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      disposed.current = true;
      controllers.current.forEach(controller => controller.abort());
      window.clearInterval(poll);
      window.clearInterval(clock);
      window.clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
      window.removeEventListener('activity:mercadolivre-progress', onProgress);
      window.removeEventListener('activity:stream-state', onStream);
    };
  }, [integrationId, focusBatchId, readSummaries, applySnapshots, readDetails]);

  useEffect(() => {
    if (refreshKey) {
      setSelectedId(refreshKey);
      readSummaries();
    }
  }, [refreshKey, readSummaries]);

  useEffect(() => {
    setDetails(null);
    if (expanded && selectedId) readDetails(selectedId, true).catch(err => setError(err.message));
  }, [expanded, selectedId, readDetails]);

  const batch = batches.find(item => String(item.id) === String(selectedId)) || batches[0];
  if (!batch && !error) return null;
  const elapsed = batch?.started_at ? Math.max(0, Math.round(((batch.finished_at ? new Date(batch.finished_at).getTime() : now) - new Date(batch.started_at).getTime()) / 1000)) : 0;
  const retryAt = batch?.available_at || batch?.next_attempt_at;

  return <Card>
    <CardHeader className="pb-3"><CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
      Execução de IA <Badge variant={batch?.failed_count > 0 ? 'destructive' : 'outline'}>{batchStage(batch)}</Badge>
    </CardTitle></CardHeader>
    <CardContent className="space-y-3">
      {error && <p role="status" className="text-sm text-amber-700">{error}</p>}
      {batch && <>
        {!focusBatchId && batches.length > 1 && <label className="flex flex-wrap items-center gap-2 text-sm">Lote
          <select className="max-w-full rounded border bg-background px-2 py-1" value={selectedId || batch.id} onChange={event => setSelectedId(event.target.value)}>
            {batches.map(item => <option key={item.id} value={item.id}>{timeLabel(item.created_at)} · {batchStage(item)}</option>)}
          </select>
        </label>}
        <div className="flex flex-wrap justify-between gap-2 text-sm"><span>Primeira passagem: <strong>{batch.processed || 0}/{batch.total || 0}</strong> pacotes analisados</span><span>Tempo: {elapsed}s</span></div>
        <div role="progressbar" aria-label="Primeira passagem" aria-valuemin={0} aria-valuemax={100} aria-valuenow={firstPassPercent(batch)} className="h-2 overflow-hidden rounded bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${firstPassPercent(batch)}%` }} />
        </div>
        <p className="text-sm">{batch.success_count || 0} sucesso(s) · {batch.failed_count || 0} falha(s) definitiva(s) · {batch.running_count || 0} em execução · {batch.retry_pending_count || 0} aguardando retentativa</p>
        {batch.retry_total > 0 && <p className="text-sm">Etapa final: {batch.retry_processed || 0}/{batch.retry_total} retentativas concluídas.</p>}
        {batch.phase === 'RETRY' && batch.status === 'PENDING' && retryAt && <p role="status" className="text-sm text-muted-foreground">Próxima tentativa a partir de {timeLabel(retryAt)}. Os resultados já concluídos estão disponíveis.</p>}
        <Button size="sm" variant="outline" onClick={() => setExpanded(value => !value)}>{expanded ? 'Ocultar detalhes' : 'Ver pacotes e erros'}</Button>
        {expanded && !details && <p className="text-sm text-muted-foreground">Carregando detalhes…</p>}
        {expanded && details && <div className="max-h-80 space-y-2 overflow-auto">
          {(details.items || []).map(item => <div key={item.pack_id} className="space-y-1 rounded border p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2"><strong>Pacote {item.pack_id}</strong><Badge variant={item.status === 'FAILED' ? 'destructive' : 'outline'}>{itemLabel(item)}</Badge></div>
            <p className="text-xs text-muted-foreground">Tentativas de IA: {item.attempts || 0}/2 · Provedor: {item.provider || '—'} · Tempo da tentativa: {Math.round((item.metrics?.duration_ms || 0) / 1000)}s</p>
            {item.error_message && <p className="break-words">{item.error_message}</p>}
            {item.status === 'RETRY_PENDING' && <p className="text-xs text-muted-foreground">Próxima tentativa: {timeLabel(item.next_attempt_at)}</p>}
            {item.status === 'FAILED' && (onReprocess && item.pedido_ids?.length
              ? <Button size="sm" variant="outline" onClick={() => callbacks.current.onReprocess(item.pedido_ids, true)}>Reprocessar este pacote</Button>
              : <Link className="text-primary underline" to={`/vendas/personalizadas/mercadolivre/${integrationId}`}>Abrir pedidos</Link>)}
          </div>)}
        </div>}
      </>}
    </CardContent>
  </Card>;
}
