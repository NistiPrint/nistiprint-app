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
import { formatAppDateTime } from '@/lib/dateTime';
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
  return formatAppDateTime(value, { fallback: value ? String(value) : '-' });
}

function toInlineJson(value) {
  if (!value || typeof value !== 'object' || Object.keys(value).length === 0) {
    return '';
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
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
    const line = [
      formatTimestamp(entry.created_at || entry.timestamp),
      entry.stage || entry.task_name || entry.source || '-',
      normalizeStatus(entry.status) || '-',
      entry.message || '',
      entry.duration_ms != null ? `${entry.duration_ms}ms` : '',
      toInlineJson(entry.payload_summary),
    ].filter(Boolean);

    return line.join(' | ');
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
      <DialogContent className="w-[96vw] max-w-[1500px] h-[92vh] overflow-hidden p-0">
        <div className="flex h-full flex-col">
          <DialogHeader className="border-b px-6 py-4">
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

          <div className="flex flex-col gap-3 px-6 py-4">
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
              Exibicao objetiva por etapa. Cada linha mostra horario, etapa, status, duracao, mensagem e contexto.
            </div>
          </div>

          <div className="min-h-0 flex-1 px-6 pb-6">
            <ScrollArea className="h-full rounded-lg border">
              {loading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : filteredLogs.length === 0 ? (
                <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
                  Nenhum log encontrado para este filtro.
                </div>
              ) : (
                <div className="min-w-[1200px] divide-y">
                  {filteredLogs.map((entry, index) => {
                    const inlineJson = toInlineJson(entry.payload_summary);

                    return (
                      <div key={entry.id || `${entry.source}-${index}`} className="px-4 py-3">
                        <div className="grid grid-cols-[180px_180px_130px_90px_1fr] gap-3 items-start">
                          <div className="text-sm font-medium whitespace-nowrap">
                            {formatTimestamp(entry.created_at || entry.timestamp)}
                          </div>

                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="capitalize">
                              {entry.stage || entry.task_name || entry.source || '-'}
                            </Badge>
                            {entry.correlation_id && (
                              <Badge variant="secondary" className="font-mono">
                                {String(entry.correlation_id).slice(0, 8)}...
                              </Badge>
                            )}
                          </div>

                          <div>
                            <Badge variant={statusVariant(entry.status)} className="gap-1 capitalize">
                              {statusIcon(entry.status)}
                              {normalizeStatus(entry.status) || 'unknown'}
                            </Badge>
                          </div>

                          <div className="text-sm text-muted-foreground whitespace-nowrap">
                            {entry.duration_ms != null ? `${entry.duration_ms} ms` : '-'}
                          </div>

                          <div className="space-y-1 min-w-0">
                            <div className="text-sm leading-6 break-words">
                              {entry.message || 'Sem mensagem'}
                            </div>

                            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                              {entry.bling_id != null && <span>Bling {entry.bling_id}</span>}
                              {entry.numero_loja && <span>{entry.numero_loja}</span>}
                            </div>

                            {inlineJson && (
                              <div className="rounded-md bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground break-all whitespace-pre-wrap">
                                {inlineJson}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </ScrollArea>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
