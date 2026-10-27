import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { groupByStage } from '@/lib/expedicaoDemandas';
import ProductionService from '@/services/ProductionService';
import { Loader2, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

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
  const [includeSimulations, setIncludeSimulations] = useState(true);

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
  const demands = useMemo(() => groupByStage(items, priority).ready, [items, priority]);

  return <div className="container mx-auto space-y-5 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-2xl font-bold">Expedição</h1><p className="text-sm text-muted-foreground">Demandas com capas e miolos prontos aguardando retirada. Depois de retirados, os produtos passam para fechamento na demanda.</p></div>
      <Button variant="outline" onClick={fetchData} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" /> Atualizar</Button>
    </div>
    <div className="flex flex-wrap gap-2" role="group" aria-label="Prioridade">
      {PRIORITIES.map((option) => <Button key={option.key} size="sm" variant={priority === option.key ? 'default' : 'outline'} onClick={() => setPriority(option.key)}>{option.label}</Button>)}
    </div>
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      <input type="checkbox" className="h-4 w-4 rounded border-input accent-primary" checked={includeSimulations} onChange={(event) => setIncludeSimulations(event.target.checked)} />
      Incluir simulações
    </label>
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
    {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Atualizando expedição…</div>}
    <div className="space-y-3">
      {demands.length === 0 && !loading && <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhuma demanda com itens para retirar no filtro selecionado.</div>}
      {demands.map((demand) => <Card key={demand.id}><CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><Link className="font-semibold text-blue-700 hover:underline" to={`/producao/${demand.simulation ? 'simulacao' : 'demanda'}/${demand.id}/dashboard`}>{demand.name}</Link>{demand.simulation && <Badge className="ml-2 bg-amber-600 text-white">Simulação</Badge>}<p className="text-xs text-muted-foreground">Entrega: {dueDate(demand.deadline)} · Coleta: {demand.collection || 'Não informada'} · {demand.priority || 'Sem prioridade'}</p></div>
          <Badge variant="outline">{demand.items.length} produto(s) para retirar</Badge>
        </div>
        <div className="grid grid-cols-3 gap-3 rounded-lg bg-muted/40 p-3 text-sm">
          <div><p className="text-muted-foreground">Capas para retirar</p><strong>{number(demand.covers)}</strong></div>
          <div><p className="text-muted-foreground">Miolos para retirar</p><strong>{number(demand.cores)}</strong></div>
          <div><p className="text-muted-foreground">Produtos (capa + miolo) para retirar</p><strong>{number(demand.match)}</strong></div>
        </div>
      </CardContent></Card>)}
    </div>
  </div>;
}
