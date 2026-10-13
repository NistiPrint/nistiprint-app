import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import {
  AlertCircle,
  ArrowRightIcon,
  Boxes,
  CheckCircle2,
  Clock3,
  RefreshCw,
  ShoppingCart,
  TrendingUp,
  Warehouse,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

const REFRESH_INTERVAL_MS = 30_000;

async function getJson(url) {
  const response = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } });
  const body = await response.json();
  if (!response.ok || body.success === false) {
    throw new Error(body.message || body.error || `Falha ao consultar ${url}`);
  }
  return body;
}

function formatCollectionTime(value) {
  if (!value) return 'Horário não informado';
  return String(value).slice(0, 5);
}

function StatCard({ title, value, detail, href, status = 'ok' }) {
  const Icon = status === 'attention' ? AlertCircle : status === 'loading' ? Clock3 : CheckCircle2;
  const statusClass = status === 'attention' ? 'text-amber-700' : status === 'loading' ? 'text-muted-foreground' : 'text-emerald-700';
  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="text-base">{title}</CardTitle>
          <Icon className={`h-5 w-5 shrink-0 ${statusClass}`} aria-hidden="true" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold">{value}</div>
        <p className="mt-1 min-h-5 text-sm text-muted-foreground">{detail}</p>
        <Link className="mt-3 inline-flex items-center text-sm font-medium text-primary hover:underline" to={href}>
          Ver detalhes <ArrowRightIcon className="ml-1 h-4 w-4" aria-hidden="true" />
        </Link>
      </CardContent>
    </Card>
  );
}

function HomePage() {
  const { hasPermission, isAdmin } = useAuth();
  const canSeeSales = isAdmin() || hasPermission('vendas', 'ler');
  const canSeeDemand = isAdmin() || hasPermission('demanda_producao', 'ler');
  const canSeeProduction = isAdmin() || hasPermission('producao', 'ler');
  const canSeeInventory = isAdmin() || hasPermission('estoque', 'ler');
  const refreshInFlight = useRef(false);
  const [snapshot, setSnapshot] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [stale, setStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const [sourceErrors, setSourceErrors] = useState([]);

  const refreshSnapshot = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    const sources = [];
    if (canSeeSales) {
      sources.push(['orders', getJson('/api/v2/pedidos/estatisticas?dias=7')]);
      sources.push(['collections', getJson('/api/v2/pedidos/canais-proximos-coleta')]);
    }
    if (canSeeDemand) {
      sources.push(['production', getJson('/api/v2/demanda_producao/dashboard-summary')]);
    }
    sources.push(['operational', getJson('/api/v2/home/operational-summary')]);

    const results = await Promise.allSettled(sources.map(([, request]) => request));
    const next = {};
    const errors = [];
    results.forEach((result, index) => {
      const [key] = sources[index];
      if (result.status === 'fulfilled') {
        next[key] = result.value;
        if (key === 'operational') {
          Object.entries(result.value.sections || {}).forEach(([section, data]) => {
            if (data.status !== 'available') errors.push({ key: section, message: data.error });
          });
        }
      }
      else errors.push({ key, message: result.reason?.message || 'Fonte indisponível' });
    });

    if (Object.keys(next).length) {
      setSnapshot(previous => ({ ...previous, ...next }));
      setLastUpdatedAt(new Date().toISOString());
    }
    setSourceErrors(errors);
    setStale(errors.length > 0);
    refreshInFlight.current = false;
    setRefreshing(false);
  }, [canSeeDemand, canSeeSales]);

  useEffect(() => {
    const initialRefresh = window.setTimeout(refreshSnapshot, 0);
    const timer = window.setInterval(refreshSnapshot, REFRESH_INTERVAL_MS);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, [refreshSnapshot]);

  const quickActions = [
    { title: 'Produtos', href: '/produtos', icon: Boxes, description: 'Gerencie seu catálogo', color: 'text-brand-aqua', bgColor: 'bg-brand-aqua-soft' },
    { title: 'Vendas', href: '/vendas', icon: ShoppingCart, description: 'Acompanhe os pedidos', color: 'text-brand-blue', bgColor: 'bg-brand-blue-soft' },
    { title: 'Estoque', href: '/estoque', icon: Warehouse, description: 'Controle de inventário', color: 'text-amber-700', bgColor: 'bg-brand-yellow-soft' },
    { title: 'Produção', href: '/producao', icon: TrendingUp, description: 'Painel operacional', color: 'text-brand-pink', bgColor: 'bg-brand-pink-soft' },
  ];

  const orderData = snapshot?.orders?.data;
  const missingDemand = orderData?.pedidos_sem_demanda;
  const collectionData = snapshot?.collections?.data?.data || snapshot?.collections?.data;
  const collections = collectionData?.canais_proximos || [];
  const nearestCollection = collections[0];
  const production = snapshot?.production;
  const productionDelayed = production?.delayed;
  const operational = snapshot?.operational?.sections || {};
  const orderOperations = operational.orders;
  const productionOperations = operational.production;
  const printOperations = operational.printing;
  const inventoryOperations = operational.inventory;
  const webhookAttention = Number(orderOperations?.webhook_attention || 0);
  const orderReconciliationOpen = Number(orderOperations?.order_reconciliation_open || 0);
  const productionErrors = Number(productionOperations?.items_with_processing_error || 0);
  const unresolvedPrints = Number(printOperations?.unresolved_sends || 0);
  const unknownPrints = Number(printOperations?.unknown_results || 0);
  const unconfirmedStockOperations = Number(inventoryOperations?.unconfirmed_operations || 0);
  const pendingStockEvents = Number(inventoryOperations?.outbox_pending || 0);
  const failedStockEvents = Number(inventoryOperations?.outbox_failed || 0);
  const stockBalanceDivergences = Number(inventoryOperations?.balance_divergences || 0);

  return (
    <div className="container mx-auto max-w-6xl px-4 py-8 md:px-6">
      <div className="mb-8">
        <h1 className="page-title">Bem-vindo(a) ao Nisti Print!</h1>
        <p className="mt-2 max-w-2xl text-lg text-muted-foreground">
          Sua plataforma completa para gerenciamento de vendas e produção.
        </p>
      </div>

      {(canSeeSales || canSeeDemand) && (
        <section aria-labelledby="home-operations-heading" className="mb-8">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="home-operations-heading" className="text-xl font-semibold">Resumo operacional</h2>
              <p className="text-sm text-muted-foreground">
                {stale
                  ? (snapshot ? 'API parcialmente indisponível; os últimos dados recebidos foram mantidos.' : 'API indisponível; ainda não há dados para mostrar.')
                  : (refreshing && !lastUpdatedAt ? 'Consultando as fontes operacionais…' : 'API conectada · atualização automática a cada 30 segundos.')}
                {lastUpdatedAt ? ` Última atualização: ${new Date(lastUpdatedAt).toLocaleTimeString('pt-BR')}.` : ''}
              </p>
            </div>
            <button
              type="button"
              onClick={refreshSnapshot}
              disabled={refreshing}
              aria-label="Atualizar resumo operacional"
              className="inline-flex min-h-10 items-center gap-2 rounded-md border px-3 text-sm hover:bg-muted disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
              Atualizar
            </button>
          </div>

          {sourceErrors.length > 0 && (
            <p role="status" className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              Resumo parcialmente desatualizado: {sourceErrors.map(error => error.key).join(', ')} indisponível(is).
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {canSeeSales && (
              <StatCard
                title="Pedidos sem demanda"
                value={Number.isFinite(missingDemand) ? missingDemand : '—'}
                detail={Number.isFinite(missingDemand) ? 'Pedidos em andamento que ainda não foram enviados à produção.' : 'Aguardando consulta de pedidos.'}
                href="/vendas/pedidos"
                status={!Number.isFinite(missingDemand) ? 'loading' : Number(missingDemand) > 0 ? 'attention' : 'ok'}
              />
            )}
            {canSeeSales && (
              <StatCard
                title="Próxima coleta"
                value={collections.length ? formatCollectionTime(collections[0].horario_coleta) : '—'}
                detail={nearestCollection
                  ? `${nearestCollection.nome || 'Canal de venda'}${Number.isFinite(nearestCollection.distancia_minutos) ? ` · em ${nearestCollection.distancia_minutos} min` : ''}`
                  : (snapshot?.collections ? 'Nenhum canal com coleta próxima.' : 'Aguardando consulta de coletas.')}
                href="/despacho"
                status={snapshot?.collections ? 'ok' : 'loading'}
              />
            )}
            {canSeeDemand && (
              <StatCard
                title="Demandas atrasadas"
                value={Number.isFinite(productionDelayed) ? productionDelayed : '—'}
                detail={Number.isFinite(productionDelayed) ? `${production?.total ?? 0} demandas no resumo de produção.` : 'Aguardando consulta de produção.'}
                href="/producao/demanda"
                status={!Number.isFinite(productionDelayed) ? 'loading' : Number(productionDelayed) > 0 ? 'attention' : 'ok'}
              />
            )}
            {orderOperations && (
              <StatCard
                title="Eventos de integração pendentes"
                value={orderOperations.status === 'available' ? webhookAttention : '—'}
                detail={orderOperations.status === 'available'
                  ? `${webhookAttention} eventos de webhook e ${orderReconciliationOpen} reconciliações de pedido.`
                  : orderOperations.error}
                href="/vendas/pedidos"
                status={orderOperations.status !== 'available' ? 'attention' : webhookAttention || orderReconciliationOpen ? 'attention' : 'ok'}
              />
            )}
            {canSeeDemand && productionOperations && (
              <StatCard
                title="Itens com falha de processamento"
                value={productionOperations.status === 'available' ? productionErrors : '—'}
                detail={productionOperations.status === 'available' ? 'Itens de demanda que precisam de análise.' : productionOperations.error}
                href="/producao/demanda"
                status={productionOperations.status !== 'available' || productionErrors > 0 ? 'attention' : 'ok'}
              />
            )}
            {canSeeProduction && printOperations && (
              <StatCard
                title="Impressões sem confirmação"
                value={printOperations.status === 'available' ? unresolvedPrints : '—'}
                detail={printOperations.status === 'available'
                  ? `${unknownPrints} com resultado desconhecido; consulte antes de reenviar.`
                  : printOperations.error}
                href="/producao/impressao"
                status={printOperations.status !== 'available' || unknownPrints > 0 ? 'attention' : 'ok'}
              />
            )}
            {canSeeInventory && inventoryOperations && (
              <StatCard
                title="Operações de estoque não confirmadas"
                value={inventoryOperations.status === 'available' ? unconfirmedStockOperations : '—'}
                detail={inventoryOperations.status === 'available'
                  ? `${unconfirmedStockOperations} operações não confirmadas · ${pendingStockEvents} eventos na outbox (${failedStockEvents} com erro).`
                  : inventoryOperations.error}
                href="/estoque"
                status={inventoryOperations.status !== 'available' || unconfirmedStockOperations > 0 || failedStockEvents > 0 ? 'attention' : 'ok'}
              />
            )}
            {canSeeInventory && inventoryOperations && (
              <StatCard
                title="Divergências entre saldo e ledger"
                value={inventoryOperations.status === 'available' ? stockBalanceDivergences : '—'}
                detail={inventoryOperations.status !== 'available'
                  ? inventoryOperations.error
                  : stockBalanceDivergences > 0
                    ? 'O saldo atual difere do último movimento registrado; revise antes de ajustar.'
                    : 'Nenhuma diferença encontrada nos saldos com movimento registrado.'}
                href="/estoque/divergencias"
                status={inventoryOperations.status !== 'available' ? 'attention' : stockBalanceDivergences > 0 ? 'attention' : 'ok'}
              />
            )}
          </div>
        </section>
      )}

      <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        {quickActions.map(action => {
          const Icon = action.icon;
          return (
            <Link key={action.title} to={action.href}>
              <Card className="group h-full border-border/80 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
                <CardHeader className="pb-3">
                  <div className={`mb-3 flex h-12 w-12 items-center justify-center rounded-xl ${action.bgColor} transition-transform duration-300 group-hover:scale-110`}>
                    <Icon className={`h-6 w-6 ${action.color}`} aria-hidden="true" />
                  </div>
                  <CardTitle className="text-lg">{action.title}</CardTitle>
                  <CardDescription className="text-sm">{action.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center text-sm font-semibold text-primary">
                    Acessar <ArrowRightIcon className="ml-1 h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default HomePage;
