import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import * as pedidoService from '@/services/pedidoService';
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  Filter,
  Loader2,
  RefreshCw,
  ShieldAlert,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

const FILTERS = [
  { value: 'all', label: 'Todos' },
  { value: 'failed', label: 'Falhas' },
  { value: 'warning', label: 'Avisos' },
];

function normalizeStatus(status) {
  return String(status || '').trim().toLowerCase();
}

function statusVariant(status) {
  const normalized = normalizeStatus(status);
  if (normalized === 'failed' || normalized === 'error') return 'destructive';
  if (normalized === 'warning') return 'outline';
  if (normalized === 'success' || normalized === 'completed' || normalized === 'done') return 'default';
  return 'secondary';
}

function statusIcon(status) {
  const normalized = normalizeStatus(status);
  if (normalized === 'failed' || normalized === 'error') return <XCircle className="h-3.5 w-3.5" />;
  if (normalized === 'warning') return <ShieldAlert className="h-3.5 w-3.5" />;
  if (normalized === 'success' || normalized === 'completed' || normalized === 'done') return <CheckCircle2 className="h-3.5 w-3.5" />;
  return <AlertCircle className="h-3.5 w-3.5" />;
}

function formatTimestamp(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('pt-BR');
}

function buildCopyText({ pedido, contexto, timeline }) {
  const header = [
    `Pedido: ${pedido?.numero_pedido || pedido?.id || '-'}`,
    `Bling ID: ${contexto?.bling_id || pedido?.pedido_bling_id || '-'}`,
    `NumeroLoja: ${contexto?.numero_loja || pedido?.codigo_pedido_externo || '-'}`,
    `Correlation IDs: ${(contexto?.correlation_ids || []).join(', ') || '-'}`,
    '',
  ];

  const body = (timeline || []).map((entry) => {
    const parts = [
      formatTimestamp(entry.created_at || entry.timestamp),
      entry.stage || entry.task_name || entry.source || '-',
      normalizeStatus(entry.status) || '-',
      entry.message || '',
      entry.duration_ms != null ? `${entry.duration_ms}ms` : '',
    ].filter(Boolean);
    return parts.join(' | ');
  });

  return [...header, ...body].join('\n');
}

export default function PedidoLogsModal({ open, onOpenChange, pedidoId, pedido }) {
  const [loading, setLoading] = useState(false);
  const [logs, setLogs] = useState([]);
  const [contexto, setContexto] = useState(null);
  const [filter, setFilter] = useState('all');

  const loadLogs = useCallback(async () => {
    if (!pedidoId) return;
    setLoading(true);
    try {
      const data = await pedidoService.getPedidoLogs(pedidoId);
      setLogs(data.timeline || []);
      setContexto(data.contexto || null);
    } catch (error) {
      toast.error(error?.message || 'Erro ao carregar logs do pedido');
    } finally {
      setLoading(false);
    }
  }, [pedidoId]);

  useEffect(() => {
    if (open) loadLogs();
  }, [open, loadLogs]);

  const filteredLogs = useMemo(() => {
    if (filter === 'all') return logs;
    return logs.filter((entry) => {
      const status = normalizeStatus(entry.status);
      if (filter === 'failed') return status === 'failed' || status === 'error';
      if (filter === 'warning') return status === 'warning';
      return true;
    });
  }, [logs, filter]);

  const handleCopyLog = async () => {
    try {
      await navigator.clipboard.writeText(buildCopyText({ pedido, contexto, timeline: filteredLogs }));
      toast.success('Log copiado para a area de transferencia');
    } catch {
      toast.error('Nao foi possivel copiar o log');
    }
  };

  const blingId = contexto?.bling_id || pedido?.cliente?.informacoes_adicionais?.bling_id || pedido?.pedido_bling_id || '-';
  const numeroLoja = contexto?.numero_loja || pedido?.codigo_pedido_externo || '-';
  const correlationIds = contexto?.correlation_ids || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[88vh] overflow-hidden">
        <DialogHeader className="pr-10">
          <DialogTitle className="flex items-center gap-2">
            <Filter className="h-5 w-5" />
            Logs do Pedido
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">Bling ID: {blingId}</Badge>
            <Badge variant="outline">NumeroLoja: {numeroLoja}</Badge>
            {correlationIds.length > 0 ? (
              correlationIds.map((cid) => (
                <Badge key={cid} variant="secondary" className="font-mono">
                  {cid.slice(0, 8)}...
                </Badge>
              ))
            ) : (
              <Badge variant="secondary">Sem correlation_id</Badge>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              {FILTERS.map((item) => (
                <Button
                  key={item.value}
                  type="button"
                  variant={filter === item.value ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setFilter(item.value)}
                >
                  {item.label}
                </Button>
              ))}
            </div>

            <div className="flex gap-2">
              <Button type="button" variant="outline" size="sm" onClick={handleCopyLog} disabled={!filteredLogs.length}>
                <Copy className="mr-2 h-4 w-4" />
                Copiar log
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={loadLogs} disabled={loading}>
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                Atualizar
              </Button>
            </div>
          </div>

          <div className="rounded-lg border bg-muted/20 p-3 text-sm text-muted-foreground">
            Timeline reversa de ingest e execucao. Use os filtros para isolar falhas e avisos.
          </div>

          <ScrollArea className="h-[62vh] pr-4">
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : filteredLogs.length === 0 ? (
              <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
                Nenhum log encontrado para este filtro.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredLogs.map((entry, index) => (
                  <div key={entry.id || `${entry.source}-${index}`} className="rounded-lg border bg-background p-4 shadow-sm">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium">
                            {formatTimestamp(entry.created_at || entry.timestamp)}
                          </span>
                          <Badge variant="outline" className="capitalize">
                            {entry.stage || entry.task_name || entry.source || '-'}
                          </Badge>
                          <Badge variant={statusVariant(entry.status)} className="gap-1 capitalize">
                            {statusIcon(entry.status)}
                            {normalizeStatus(entry.status) || 'unknown'}
                          </Badge>
                          {entry.duration_ms != null && (
                            <Badge variant="secondary">{entry.duration_ms} ms</Badge>
                          )}
                        </div>
                        <div className="text-sm leading-6 text-foreground">
                          {entry.message || 'Sem mensagem'}
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        {entry.correlation_id && (
                          <Badge variant="secondary" className="font-mono">
                            Corr: {String(entry.correlation_id).slice(0, 8)}...
                          </Badge>
                        )}
                        {entry.bling_id != null && <Badge variant="outline">Bling {entry.bling_id}</Badge>}
                        {entry.numero_loja && <Badge variant="outline">{entry.numero_loja}</Badge>}
                      </div>
                    </div>

                    {entry.payload_summary && Object.keys(entry.payload_summary).length > 0 && (
                      <pre className="mt-3 overflow-x-auto rounded-md bg-muted p-3 text-xs text-muted-foreground">
                        {JSON.stringify(entry.payload_summary, null, 2)}
                      </pre>
                    )}

                    {entry.raw && entry.source === 'task_execution_logs' && (
                      <pre className="mt-3 overflow-x-auto rounded-md bg-muted/60 p-3 text-[11px] text-muted-foreground">
                        {JSON.stringify({
                          task_name: entry.raw.task_name,
                          task_type: entry.raw.task_type,
                          status: entry.raw.status,
                          error_message: entry.raw.error_message,
                        }, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}
