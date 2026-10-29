import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { demandsForExpedition } from '@/lib/expedicaoDemandas';
import ProductionService from '@/services/ProductionService';
import { ArrowRight, Loader2, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const PRIORITIES = [
  { key: 'ALL', label: 'Todas as prioridades' },
  { key: 'URGENTE', label: 'Urgente' },
  { key: 'FLEX', label: 'Flex' },
  { key: 'NORMAL', label: 'Normal' },
];
const number = (value) => new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 4 }).format(Number(value) || 0);
const dueDate = (value) => value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString('pt-BR') : 'Sem prazo';
export default function ExpedicaoDashboardPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [priority, setPriority] = useState('ALL');
  const [includeSimulations, setIncludeSimulations] = useState(false);
  const [savingWithdrawal, setSavingWithdrawal] = useState('');
  const pendingOperations = useRef(new Map());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await ProductionService.getConsolidadoProducao({ agrupado: false, incluir_simulacoes: includeSimulations });
      if (!response.success) throw new Error(response.message || 'Erro ao carregar dados da expedição.');
      setItems(response.data || []);
    } catch (err) {
      setError(err.response?.data?.message || err.message || 'Erro ao carregar dados da expedição.');
    } finally {
      setLoading(false);
    }
  }, [includeSimulations]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // A expedição só age sobre capas e miolos prontos que ainda não foram retirados.
  const demands = useMemo(() => demandsForExpedition(items, priority), [items, priority]);

  const getPendingOperation = (key, content) => {
    let pending = pendingOperations.current.get(key);
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (!pending && saved?.content === content) pending = saved;
    } catch { /* sessão sem estado recuperável */ }
    if (!pending || pending.content !== content) {
      pending = { content, operation_id: crypto.randomUUID() };
      pendingOperations.current.set(key, pending);
      try { sessionStorage.setItem(key, JSON.stringify(pending)); } catch { /* sessão indisponível */ }
    }
    return pending;
  };

  const clearPendingOperation = (key) => {
    pendingOperations.current.delete(key);
    try { sessionStorage.removeItem(key); } catch { /* sessão indisponível */ }
  };

  const registerDemandWithdrawal = async (demand, component) => {
    const availableField = component === 'capas' ? 'capas_disponiveis' : 'miolos_disponiveis';
    const field = component === 'capas' ? 'expedicao_capas_retiradas_qtd' : 'expedicao_miolos_retirados_qtd';
    const entries = demand.items
      .map((item) => ({ item, quantity: Number(item[availableField]) || 0 }))
      .filter((entry) => entry.quantity > 0);
    if (!entries.length) return;
    if (entries.some((entry) => !Number.isInteger(entry.quantity))) {
      toast.error('Há saldo fracionado nesta demanda. Atualize os dados antes de registrar a retirada total.');
      return;
    }

    const total = entries.reduce((sum, entry) => sum + entry.quantity, 0);
    const savingKey = `${demand.id}:${component}`;
    setSavingWithdrawal(savingKey);
    try {
      if (demand.simulation) {
        const operationKey = `expedition-withdrawal:${savingKey}`;
        const updates = entries.map(({ item, quantity }) => ({
          item_id: item.item_id,
          producao_incremental: { [field]: quantity },
        }));
        const content = JSON.stringify({ demandId: demand.id, component, updates });
        const pending = getPendingOperation(operationKey, content);
        const detailResponse = await fetch(`/api/v2/demanda-simulacoes/${demand.id}`);
        const detail = await detailResponse.json();
        if (!detailResponse.ok || !detail.success || !detail.demanda?.version) {
          throw new Error(detail.message || 'Não foi possível atualizar a versão da simulação.');
        }
        const response = await fetch(`/api/v2/demanda-simulacoes/${demand.id}/acoes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            version: detail.demanda.version,
            operation_id: pending.operation_id,
            action: 'producao',
            payload: { updates },
          }),
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
          const requestError = new Error(result.message || 'Não foi possível registrar as retiradas na simulação.');
          requestError.status = response.status;
          throw requestError;
        }
        clearPendingOperation(operationKey);
      } else {
        for (const { item, quantity } of entries) {
          const operationKey = `expedition-withdrawal:${demand.id}:${item.item_id}:${component}`;
          const content = JSON.stringify({ demandId: demand.id, itemId: item.item_id, component, quantity });
          const pending = getPendingOperation(operationKey, content);
          await ProductionService.registrarRetiradaExpedicao(
            demand.id, item.item_id, quantity, pending.operation_id, component,
          );
          clearPendingOperation(operationKey);
        }
      }
      toast.success(`${number(total)} ${component === 'capas' ? 'capa(s)' : 'miolo(s)'} registrada(s) como retirada${demand.simulation ? ' na simulação' : ''}.`);
      await fetchData();
    } catch (err) {
      if ((err.status ?? err.response?.status) === 409) {
        toast.error('O saldo mudou. Atualizei a lista antes de uma nova tentativa.');
      } else {
        toast.error(err.response?.data?.message || err.message || 'Falha ao registrar a retirada.');
      }
      await fetchData();
    } finally {
      setSavingWithdrawal('');
    }
  };

  return <div className="container mx-auto space-y-5 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-2xl font-bold">Expedição</h1><p className="text-sm text-muted-foreground">Demandas com capas ou miolos prontos aguardando retirada. Cada componente pode sair em um momento diferente.</p></div>
      <Button variant="outline" onClick={fetchData} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" /> Atualizar</Button>
    </div>
    <div className="flex flex-wrap gap-2" role="group" aria-label="Prioridade">
      {PRIORITIES.map((option) => <Button key={option.key} size="sm" variant={priority === option.key ? 'default' : 'outline'} onClick={() => setPriority(option.key)}>{option.label}</Button>)}
      <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground"><input type="checkbox" className="h-4 w-4 accent-primary" checked={includeSimulations} onChange={(event) => setIncludeSimulations(event.target.checked)} /> Incluir simulações</label>
    </div>
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
    {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Atualizando expedição…</div>}
    <div className="space-y-3">
      {demands.length === 0 && !loading && <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhuma demanda encontrada no filtro selecionado.</div>}
      {demands.map((demand) => <Card key={demand.id} className={`transition-colors ${demand.needsAction ? 'hover:border-primary/60' : 'opacity-45'}`}><CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><span className="font-semibold text-blue-700">{demand.name}</span>{demand.simulation && <Badge className="ml-2 bg-amber-600 text-white">Simulação</Badge>}<p className="text-xs text-muted-foreground">Entrega: {dueDate(demand.deadline)} · Coleta: {demand.collection || 'Não informada'} · {demand.priority || 'Sem prioridade'}</p></div>
          <div className="flex items-center gap-2">
            <Badge variant={demand.needsAction ? 'default' : 'outline'}>{demand.needsAction ? 'Retirada pendente' : 'Sem ação'}</Badge>
            <Button asChild size="sm" variant="outline">
              <Link to={`/producao/${demand.simulation ? 'simulacao' : 'demanda'}/${demand.id}/dashboard`} aria-label={`Ir para a demanda ${demand.name}`}>
                Ir <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-4 py-3">
            <div><p className="text-sm text-muted-foreground">Capas para retirar</p><strong className="text-2xl tabular-nums">{number(demand.covers)}</strong></div>
            <Button size="sm" variant="outline" disabled={!demand.covers || Boolean(savingWithdrawal)} onClick={() => registerDemandWithdrawal(demand, 'capas')}>{savingWithdrawal === `${demand.id}:capas` && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}Retirar tudo</Button>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-4 py-3">
            <div><p className="text-sm text-muted-foreground">Miolos para retirar</p><strong className="text-2xl tabular-nums">{number(demand.cores)}</strong></div>
            <Button size="sm" variant="outline" disabled={!demand.cores || Boolean(savingWithdrawal)} onClick={() => registerDemandWithdrawal(demand, 'miolos')}>{savingWithdrawal === `${demand.id}:miolos` && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}Retirar tudo</Button>
          </div>
        </div>
      </CardContent></Card>)}
    </div>
  </div>;
}
