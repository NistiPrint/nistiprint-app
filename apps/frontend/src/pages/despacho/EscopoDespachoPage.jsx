import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useProducaoSidebar } from '@/lib/hooks/useProducaoSidebar';
import { ArrowLeft, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

// Escopo de despacho — N1 da navegacao por contexto.
// Contrato: docs/specs/02-domains/despacho/spec.md, secao "Escopo composto e lancamento"
//
// O escopo e (no, horizonte). Nao ha checkbox por pedido no fluxo normal:
// a lista abaixo e para conferencia, nao para selecao manual.

const HORIZONTE_STEPS = ['atrasado', 'hoje', 'amanha', 'depois', 'sem_prazo'];
const HORIZONTE_LABEL = {
  atrasado: 'Atrasado',
  hoje: 'Hoje',
  amanha: 'Amanhã',
  depois: 'Depois',
  sem_prazo: 'Sem prazo',
};

function parseIntOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = parseInt(value, 10);
  return Number.isNaN(n) ? null : n;
}

export default function EscopoDespachoPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  // Mesma sidebar da operacao Industrial.
  useProducaoSidebar();

  const integrationId = parseIntOrNull(searchParams.get('integration_id'));
  const modalidadeId = parseIntOrNull(searchParams.get('modalidade_id'));
  const marketplaceNome = searchParams.get('marketplace_nome') || 'Origem não resolvida';
  const modalidadeNome = searchParams.get('modalidade_nome') || 'Modalidade não classificada';

  // Default: atrasado + hoje. Estender o horizonte e uma decisao de um clique.
  const [horizonteAte, setHorizonteAte] = useState(1); // indice em HORIZONTE_STEPS, inclusive
  const [dados, setDados] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lancando, setLancando] = useState(false);
  const [erro, setErro] = useState(null);

  const horizonte = useMemo(() => HORIZONTE_STEPS.slice(0, horizonteAte + 1), [horizonteAte]);

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const hoje = new Date().toISOString().slice(0, 10);
      const params = new URLSearchParams();
      if (integrationId !== null) params.set('integration_id', integrationId);
      if (modalidadeId !== null) params.set('modalidade_id', modalidadeId);
      horizonte.forEach((h) => params.append('horizonte', h));
      params.set('data', hoje);

      const res = await fetch(`/api/v2/despacho/escopo?${params.toString()}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar escopo');
      setDados(json.data);
    } catch (err) {
      setErro(err.message || 'Erro ao carregar');
    } finally {
      setLoading(false);
    }
  }, [integrationId, modalidadeId, horizonte]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const lancar = async () => {
    setLancando(true);
    try {
      const hoje = new Date().toISOString().slice(0, 10);
      const res = await fetch('/api/v2/despacho/lancar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          integration_id: integrationId,
          modalidade_id: modalidadeId,
          horizonte,
          data: hoje,
        }),
      });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao lançar demanda');

      const { demanda_codigo, total_pedidos, complementar } = json.data;
      toast.success(
        complementar
          ? `Lote complementar lançado: ${demanda_codigo} (${total_pedidos} pedidos)`
          : `Demanda lançada: ${demanda_codigo} (${total_pedidos} pedidos)`
      );
      navigate('/despacho');
    } catch (err) {
      toast.error(err.message || 'Erro ao lançar demanda');
    } finally {
      setLancando(false);
    }
  };

  const total = dados?.total ?? 0;

  return (
    <div className="p-6">
      <button
        type="button"
        onClick={() => navigate('/despacho')}
        className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Voltar para a torre de despacho
      </button>

      <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <span>{marketplaceNome}</span>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">{modalidadeNome}</span>
      </div>

      <Card className="mb-6">
        <CardContent className="py-5">
          <div className="mb-3 text-sm font-medium">Horizonte</div>
          <div className="flex flex-wrap gap-2">
            {HORIZONTE_STEPS.map((step, idx) => (
              <button
                key={step}
                type="button"
                onClick={() => setHorizonteAte(idx)}
                className={
                  'rounded-full border px-3 py-1 text-xs transition-colors ' +
                  (idx <= horizonteAte
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground hover:border-primary/40')
                }
              >
                até {HORIZONTE_LABEL[step]}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Compare o total abaixo com a tela do marketplace antes de lançar.
          </p>
        </CardContent>
      </Card>

      {erro && (
        <Card className="mb-4 border-destructive/50">
          <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardContent className="flex items-center justify-between py-5">
          <div>
            <div className="text-3xl font-semibold leading-none">{loading ? '—' : total}</div>
            <div className="text-xs text-muted-foreground mt-1">pedidos no escopo selecionado</div>
          </div>
          <Button size="lg" disabled={loading || lancando || total === 0} onClick={lancar}>
            {lancando ? 'Lançando…' : `Conferir e lançar (${total})`}
          </Button>
        </CardContent>
      </Card>

      <div className="mb-2 text-sm font-medium">Pedidos no escopo</div>
      {loading && (
        <div className="space-y-2">
          <div className="h-10 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-10 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-10 w-full animate-pulse rounded-md bg-muted" />
        </div>
      )}

      {!loading && dados?.pedidos?.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Nenhum pedido neste escopo.
          </CardContent>
        </Card>
      )}

      {!loading && dados?.pedidos?.length > 0 && (
        <div className="overflow-hidden rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Pedido</th>
                <th className="px-3 py-2 font-medium">Cliente</th>
                <th className="px-3 py-2 font-medium">Total</th>
                <th className="px-3 py-2 font-medium">Prazo</th>
                <th className="px-3 py-2 font-medium">Método de envio</th>
              </tr>
            </thead>
            <tbody>
              {dados.pedidos.map((pedido) => (
                <tr key={pedido.id} className="border-t">
                  <td className="px-3 py-2">
                    {pedido.numero_pedido || pedido.codigo_pedido_externo}
                  </td>
                  <td className="px-3 py-2">{pedido.cliente_nome || '—'}</td>
                  <td className="px-3 py-2">
                    {pedido.total_pedido != null
                      ? Number(pedido.total_pedido).toLocaleString('pt-BR', {
                          style: 'currency',
                          currency: 'BRL',
                        })
                      : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {pedido.data_limite_envio
                      ? new Date(pedido.data_limite_envio).toLocaleDateString('pt-BR')
                      : 'não informado'}
                  </td>
                  <td className="px-3 py-2">
                    {pedido.metodo_envio_rotulo ? (
                      pedido.metodo_envio_rotulo
                    ) : (
                      <Badge variant="outline" className="text-[10px] border-amber-400 text-amber-700">
                        não classificado
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
