import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { useProducaoSidebar } from '@/lib/hooks/useProducaoSidebar';
import { Clock, Package, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// Torre de despacho — N0 da navegacao por contexto.
// Contrato: docs/specs/02-domains/despacho/spec.md
//
// Nunca exibe lista de pedidos diretamente: so a arvore de totalizadores
// (marketplace -> modalidade -> prazo). Clicar num no leva ao escopo (N1),
// que e onde a lista de pedidos realmente aparece, ja filtrada pela regra.

const BUCKET_LABEL = {
  atrasado: 'Atrasado',
  hoje: 'Hoje',
  amanha: 'Amanhã',
  depois: 'Depois',
  sem_prazo: 'Sem prazo',
};

function formatCompromisso(iso) {
  if (!iso) return null;
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return null;
  return data.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function ModalidadeCard({ marketplace, modalidade, onAbrir }) {
  const atrasadoBucket = modalidade.buckets?.find((b) => b.bucket === 'atrasado');
  const temAtrasado = atrasadoBucket && atrasadoBucket.qtd_pedidos > 0;
  const naoClassificada = modalidade.modalidade_id === null;
  const compromisso = formatCompromisso(modalidade.compromisso_mais_proximo);

  return (
    <Card
      className={
        'cursor-pointer transition-colors hover:border-primary/60 ' +
        (temAtrasado ? 'border-l-4 border-l-orange-500' : naoClassificada ? 'border-l-4 border-l-amber-400' : '')
      }
      onClick={() =>
        onAbrir({
          integrationId: marketplace.integration_id,
          modalidadeId: modalidade.modalidade_id,
          nomeMarketplace: marketplace.nome,
          nomeModalidade: modalidade.nome,
        })
      }
    >
      <CardContent className="py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm">{modalidade.nome}</span>
              {modalidade.tipo_prazo === 'RELATIVO' && (
                <Badge variant="outline" className="text-[10px]">tempo real</Badge>
              )}
              {naoClassificada && (
                <Badge variant="outline" className="text-[10px] border-amber-400 text-amber-700">
                  prioridade máxima
                </Badge>
              )}
            </div>
            {compromisso && (
              <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                próximo compromisso {compromisso}
              </div>
            )}
          </div>
          <div className="text-right">
            <div className="text-2xl font-semibold leading-none">{modalidade.qtd_pedidos}</div>
            <div className="text-[11px] text-muted-foreground">pedidos</div>
          </div>
        </div>

        {modalidade.buckets?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
            {modalidade.buckets
              .slice()
              .sort((a, b) => {
                const order = ['atrasado', 'hoje', 'amanha', 'depois', 'sem_prazo'];
                return order.indexOf(a.bucket) - order.indexOf(b.bucket);
              })
              .map((bucket) => (
                <span
                  key={bucket.bucket}
                  className={
                    'text-xs rounded-full px-2 py-0.5 ' +
                    (bucket.bucket === 'atrasado' && bucket.qtd_pedidos > 0
                      ? 'bg-orange-100 text-orange-800'
                      : 'bg-muted text-muted-foreground')
                  }
                >
                  {BUCKET_LABEL[bucket.bucket] || bucket.bucket}: {bucket.qtd_pedidos}
                </span>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MarketplaceGroup({ marketplace, onAbrirModalidade }) {
  return (
    <div className="mb-8">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-base font-semibold">{marketplace.nome}</h2>
        <div className="flex items-center gap-1 text-sm text-muted-foreground">
          <Package className="h-4 w-4" />
          {marketplace.qtd_pedidos} pedidos em aberto
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {marketplace.modalidades.map((modalidade) => (
          <ModalidadeCard
            key={String(modalidade.modalidade_id)}
            marketplace={marketplace}
            modalidade={modalidade}
            onAbrir={onAbrirModalidade}
          />
        ))}
      </div>
    </div>
  );
}

export default function TorreDespachoPage() {
  const [arvore, setArvore] = useState(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(null);
  const navigate = useNavigate();

  // Mesma sidebar da operacao Industrial.
  useProducaoSidebar();

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const hoje = new Date().toISOString().slice(0, 10);
      const res = await fetch(`/api/v2/despacho/arvore?data=${hoje}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar árvore de despacho');
      setArvore(json.data);
    } catch (err) {
      setErro(err.message || 'Erro ao carregar');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    carregar();
    // Atualiza periodicamente: pedidos novos precisam aparecer sem o usuário
    // ter que dar refresh manual (spec: notificação destacada de novo pedido).
    const interval = setInterval(carregar, 60_000);
    return () => clearInterval(interval);
  }, [carregar]);

  const abrirEscopo = ({ integrationId, modalidadeId, nomeMarketplace, nomeModalidade }) => {
    const params = new URLSearchParams();
    if (integrationId !== null && integrationId !== undefined) params.set('integration_id', integrationId);
    if (modalidadeId !== null && modalidadeId !== undefined) params.set('modalidade_id', modalidadeId);
    params.set('marketplace_nome', nomeMarketplace || '');
    params.set('modalidade_nome', nomeModalidade || '');
    navigate(`/despacho/escopo?${params.toString()}`);
  };

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Torre de despacho</h1>
          <p className="text-sm text-muted-foreground">
            Ordenado por tempo até o compromisso logístico
          </p>
        </div>
        <button
          type="button"
          onClick={carregar}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className={'h-4 w-4 ' + (loading ? 'animate-spin' : '')} />
          Atualizar
        </button>
      </div>

      {erro && (
        <Card className="mb-4 border-destructive/50">
          <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
        </Card>
      )}

      {loading && !arvore && (
        <div className="space-y-4">
          <div className="h-24 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-24 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-24 w-full animate-pulse rounded-md bg-muted" />
        </div>
      )}

      {arvore && arvore.marketplaces.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Nenhum pedido em aberto no momento.
          </CardContent>
        </Card>
      )}

      {arvore &&
        arvore.marketplaces.map((marketplace) => (
          <MarketplaceGroup
            key={String(marketplace.integration_id)}
            marketplace={marketplace}
            onAbrirModalidade={abrirEscopo}
          />
        ))}
    </div>
  );
}
