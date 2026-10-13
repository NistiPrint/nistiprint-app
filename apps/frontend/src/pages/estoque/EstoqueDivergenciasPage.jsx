import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const PAGE_SIZE = 50;

function formatQuantity(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('pt-BR', { maximumFractionDigits: 4 })
    : '—';
}

function formatDate(value) {
  if (!value) return 'Data não informada';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Data inválida' : date.toLocaleString('pt-BR');
}

export default function EstoqueDivergenciasPage() {
  const [data, setData] = useState({ rows: [], count: null, offset: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const requestInFlight = useRef(false);

  const loadPage = useCallback(async (offset = 0) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setLoading(true);
    try {
      const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      const response = await fetch(`/api/v2/estoque/divergencias-ledger?${query}`, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      const body = await response.json();
      if (!response.ok || body.success === false) {
        throw new Error(body.error || body.message || 'Não foi possível consultar as divergências.');
      }
      setData({ rows: body.data || [], count: Number(body.count || 0), offset: Number(body.offset || 0) });
      setLastUpdatedAt(new Date().toISOString());
      setError(null);
    } catch (requestError) {
      setError(requestError.message || 'Falha ao consultar divergências.');
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => loadPage(0), 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadPage]);

  const previousOffset = Math.max(0, data.offset - PAGE_SIZE);
  const nextOffset = data.offset + PAGE_SIZE;
  const hasNextPage = nextOffset < data.count;
  const hasPreviousPage = data.offset > 0;

  return (
    <div className="container mx-auto max-w-6xl space-y-5 px-4 py-8 md:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title">Divergências de saldo</h1>
          <p className="mt-2 max-w-3xl text-muted-foreground">
            Comparação do saldo atual com o saldo depois do último movimento registrado para cada produto e depósito.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadPage(data.offset)}
          disabled={loading}
          aria-label="Atualizar divergências de saldo"
          className="inline-flex min-h-10 items-center gap-2 rounded-md border px-3 text-sm hover:bg-muted disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          Atualizar
        </button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {data.count == null || error ? <AlertCircle className="h-5 w-5 text-amber-700" aria-hidden="true" /> : data.count > 0 ? <AlertCircle className="h-5 w-5 text-amber-700" aria-hidden="true" /> : <CheckCircle2 className="h-5 w-5 text-emerald-700" aria-hidden="true" />}
            {data.count == null
              ? (error ? 'Divergências indisponíveis' : 'Consultando divergências…')
              : `${data.count} divergência(s) encontrada(s)`}
          </CardTitle>
          <CardDescription>
            {lastUpdatedAt ? `Consulta em ${formatDate(lastUpdatedAt)}.` : 'Aguardando consulta.'}
            {error ? ' A consulta falhou; os últimos dados recebidos foram mantidos.' : ''}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <p role="status" className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {error}
            </p>
          )}

          {data.count === 0 && !error ? (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900">
              Nenhuma divergência foi encontrada entre os saldos atuais e os últimos movimentos com saldo registrado.
            </div>
          ) : data.rows.length > 0 ? (
            <>
              <p className="mb-3 text-sm text-muted-foreground">
                Revise o histórico antes de corrigir. Esta tela identifica diferenças e não altera o estoque.
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Produto</TableHead>
                      <TableHead>Depósito</TableHead>
                      <TableHead className="text-right">Saldo atual</TableHead>
                      <TableHead className="text-right">Último movimento</TableHead>
                      <TableHead className="text-right">Diferença</TableHead>
                      <TableHead>Movimento registrado</TableHead>
                      <TableHead>Ação</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.rows.map(row => (
                      <TableRow key={`${row.produto_id}:${row.deposito_id}`}>
                        <TableCell>
                          <div className="font-medium">{row.produto_nome || `Produto ${row.produto_id}`}</div>
                          <div className="text-xs text-muted-foreground">SKU {row.produto_sku || 'não informado'}</div>
                        </TableCell>
                        <TableCell>{row.deposito_nome || `Depósito ${row.deposito_id}`}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatQuantity(row.saldo_atual)}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatQuantity(row.saldo_ultimo_movimento)}</TableCell>
                        <TableCell className="text-right font-semibold tabular-nums">{formatQuantity(row.diferenca)}</TableCell>
                        <TableCell>{formatDate(row.movimento_registrado_em)}</TableCell>
                        <TableCell>
                          <Link
                            className="inline-flex min-h-9 items-center text-sm font-medium text-primary hover:underline"
                            to="/estoque/historico"
                            aria-label={`Abrir histórico do produto ${row.produto_nome || row.produto_id}`}
                          >
                            Abrir histórico
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm text-muted-foreground">
                  Exibindo {data.offset + 1}–{Math.min(data.offset + data.rows.length, data.count)} de {data.count}
                </span>
                <div className="flex gap-2">
                  <button type="button" onClick={() => loadPage(previousOffset)} disabled={!hasPreviousPage || loading} className="inline-flex min-h-9 items-center gap-1 rounded-md border px-3 text-sm disabled:opacity-50">
                    <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Anterior
                  </button>
                  <button type="button" onClick={() => loadPage(nextOffset)} disabled={!hasNextPage || loading} className="inline-flex min-h-9 items-center gap-1 rounded-md border px-3 text-sm disabled:opacity-50">
                    Próxima <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </>
          ) : null}

          <div className="mt-5 border-t pt-4 text-sm text-muted-foreground">
            Compare o movimento e a operação de origem antes de ajustar. Se a diferença for legítima, registre a correção pelo fluxo normal de estoque.
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
