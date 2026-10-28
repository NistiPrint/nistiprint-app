import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertTriangle, ChevronRight, History, LayoutGrid, LayoutList, List, Loader2, Minus, Plus, Search, TowerControl } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { dataCurta as date, numero as number } from '@/lib/formatoProducao';
import PrevisaoMiolosTorre from './PrevisaoMiolosTorre';

const demandPath = (row) => `/producao/${row.simulacao ? 'simulacao' : 'demanda'}/${row.demanda_id ?? row.id}/dashboard`;
const SimulationBadge = ({ show }) => show ? <Badge className="ml-2 bg-amber-600 text-white">Simulação</Badge> : null;
const stageName = (tipo, capaSubTab) => tipo === 'miolo' ? 'miolos' : capaSubTab === 'impressas' ? 'capas impressas' : 'capas acabadas';

const COLUMNS = [
  { key: 'estoque_disponivel', short: 'Disp.', label: 'Estoque disponível' },
  { key: 'estoque_fisico', short: 'Físico', label: 'Estoque físico', muted: true },
  { key: 'estoque_reservado', short: 'Reserv.', label: 'Estoque reservado', muted: true },
  { key: 'demanda_pendente', short: 'Pendente', label: 'Demanda pendente' },
  { key: 'coberto_estoque', short: 'Coberto', label: 'Coberto pelo estoque', muted: true },
  { key: 'falta_demandas', short: 'Falta', label: 'Falta para demandas', highlight: 'text-red-700' },
  { key: 'reposicao_minimo', short: 'Repor', label: 'Reposição do estoque mínimo', highlight: 'text-amber-700' },
];

export default function ProductionPlanningViews({
  tipo, capaSubTab, setCapaSubTab, view, setView, planning, loading, error,
  products, filter, setFilter, inputs, onInputChange, onProduction, onRemoval, onLog, onRefresh,
  includeSimulations, setIncludeSimulations, previsao,
}) {
  const [expanded, setExpanded] = useState(() => new Set());
  const toggleExpanded = (id) => setExpanded((current) => {
    const next = new Set(current);
    if (!next.delete(String(id))) next.add(String(id));
    return next;
  });

  const stockById = useMemo(() => new Map(products.map((product) => [String(product.id), product])), [products]);
  const plannedProducts = planning?.products || [];
  const unmapped = planning?.unmapped || [];
  const query = filter.trim().toLocaleLowerCase('pt-BR');
  const visibleProducts = plannedProducts.filter((product) => !query || [product.name, product.sku, ...product.demandas.map((row) => row.demanda_nome)]
    .some((value) => String(value || '').toLocaleLowerCase('pt-BR').includes(query)));
  const demands = (() => {
    const grouped = new Map();
    for (const product of plannedProducts) {
      for (const row of product.demandas) {
        const key = String(row.demanda_id);
        if (!grouped.has(key)) grouped.set(key, {
          id: row.demanda_id, name: row.demanda_nome, deadline: row.data_entrega,
          priority: row.prioridade, simulacao: row.simulacao, pending: 0, covered: 0, shortage: 0, rows: [], unmapped: [],
        });
        const demand = grouped.get(key);
        demand.pending += row.pendente;
        demand.covered += row.coberto_estoque;
        demand.shortage += row.falta_apos_estoque;
        demand.rows.push({ ...row, product_id: product.product_id, product_name: product.name, sku: product.sku });
      }
    }
    for (const row of unmapped) {
      const key = String(row.demanda_id);
      if (!grouped.has(key)) grouped.set(key, {
        id: row.demanda_id, name: row.demanda_nome, deadline: null,
        priority: 0, simulacao: row.simulacao, pending: 0, covered: 0, shortage: 0, rows: [], unmapped: [],
      });
      grouped.get(key).unmapped.push(row);
    }
    return [...grouped.values()].sort((a, b) => b.priority - a.priority ||
      (a.deadline || '9999-12-31').localeCompare(b.deadline || '9999-12-31') || String(a.id).localeCompare(String(b.id)));
  })();
  const visibleDemands = demands.filter((demand) => !query || [demand.name, String(demand.id), ...demand.rows.map((row) => `${row.product_name} ${row.sku}`)]
    .some((value) => String(value || '').toLocaleLowerCase('pt-BR').includes(query)));
  const totals = plannedProducts.reduce((sum, row) => ({
    shortage: sum.shortage + row.falta_demandas,
    replenishment: sum.replenishment + row.reposicao_minimo,
  }), { shortage: 0, replenishment: 0 });
  const stage = stageName(tipo, capaSubTab);
  const emPrevisao = view === 'previsao';

  return <div className="space-y-3">
    <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h1 className="text-xl font-bold leading-tight">Controle de produção de {tipo === 'miolo' ? 'miolos' : 'capas'}</h1>
        <p className="text-xs text-muted-foreground">Cobertura projetada com o estoque disponível; nenhuma reserva é criada pelo planejamento.</p>
      </div>
    </div>
    {!emPrevisao && <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
      <span className="text-muted-foreground">Falta para demandas <strong className="ml-1 text-base tabular-nums text-red-700">{number(totals.shortage)}</strong></span>
      <span className="text-muted-foreground">Reposição do estoque mínimo <strong className="ml-1 text-base tabular-nums text-amber-700">{number(totals.replenishment)}</strong></span>
      <span className="text-xs text-muted-foreground">{visibleProducts.length} de {plannedProducts.length} {stage}</span>
    </div>}
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        {tipo === 'capa' && <div className="flex gap-1.5" role="group" aria-label="Etapa das capas">
          <Button size="sm" variant={capaSubTab === 'impressas' ? 'default' : 'outline'} onClick={() => setCapaSubTab('impressas')}>Impressas</Button>
          <Button size="sm" variant={capaSubTab === 'acabadas' ? 'default' : 'outline'} onClick={() => setCapaSubTab('acabadas')}>Acabadas</Button>
        </div>}
        {tipo === 'capa' && <div className="h-5 w-px bg-border" />}
        <div className="flex gap-1" role="tablist" aria-label="Visualização do planejamento">
          <Button size="icon" className="h-8 w-8" role="tab" aria-selected={view === 'produto'} variant={view === 'produto' ? 'default' : 'outline'} title="Por produto" onClick={() => setView('produto')}><List className="h-4 w-4" /></Button>
          <Button size="icon" className="h-8 w-8" role="tab" aria-selected={view === 'demanda'} variant={view === 'demanda' ? 'default' : 'outline'} title="Por demanda" onClick={() => setView('demanda')}><LayoutList className="h-4 w-4" /></Button>
          <Button size="icon" className="h-8 w-8" role="tab" aria-selected={view === 'grade'} variant={view === 'grade' ? 'default' : 'outline'} title="Grade" onClick={() => setView('grade')}><LayoutGrid className="h-4 w-4" /></Button>
          {tipo === 'miolo' && previsao && <Button size="sm" className="h-8 gap-1.5" role="tab" aria-selected={emPrevisao} variant={emPrevisao ? 'default' : 'outline'} title="Miolos previstos pelos lotes ainda não publicados" onClick={() => setView('previsao')}><TowerControl className="h-4 w-4" /> Previsão</Button>}
        </div>
      </div>
      <div className="flex gap-2 w-full sm:w-auto">
        <div className="relative flex-1 sm:w-64"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="h-9 pl-8" placeholder="Buscar produto ou demanda" value={filter} onChange={(event) => setFilter(event.target.value)} />
        </div>
        {!emPrevisao && <label className="flex items-center gap-2 whitespace-nowrap text-sm text-muted-foreground">
          <input type="checkbox" className="h-4 w-4 rounded border-input accent-primary" checked={includeSimulations} onChange={(event) => setIncludeSimulations(event.target.checked)} />
          Incluir simulações
        </label>}
        <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading || previsao?.loading}>Atualizar</Button>
      </div>
    </div>
    {!emPrevisao && error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
    {!emPrevisao && loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Atualizando planejamento…</div>}
    {!emPrevisao && unmapped.length > 0 && <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
      <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> {unmapped.length} item(ns) sem vínculo confiável nesta etapa</div>
      <details className="mt-1"><summary className="cursor-pointer text-xs font-medium">Ver itens afetados — não entram na sugestão de {tipo === 'capa' && capaSubTab === 'impressas' ? 'impressão' : 'produção'}</summary>
        <ul className="mt-2 space-y-1 pl-4 list-disc">{unmapped.map((row) => <li key={`${row.demanda_id}-${row.item_id}`}><Link className="underline" to={demandPath(row)}>{row.demanda_nome}</Link><SimulationBadge show={row.simulacao} />: {row.item_nome} — {row.motivo}</li>)}</ul>
      </details>
    </div>}
    {view === 'produto' ? <div role="tabpanel">
      {visibleProducts.length === 0 ? <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhum produto encontrado nesta etapa.</div>
        : <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-background shadow-[inset_0_-1px_0_hsl(var(--border))]">
              <TableRow>
                <TableHead className="h-9 w-[30%] min-w-[200px] px-3">Produto</TableHead>
                {COLUMNS.map((column) => <TableHead key={column.key} className="h-9 w-[70px] px-2 text-right text-xs" title={column.label}>{column.short}</TableHead>)}
                <TableHead className="h-9 w-[168px] px-3 text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleProducts.map((product) => {
                const stockProduct = stockById.get(String(product.product_id)) || { id: product.product_id, name: product.name, sku: product.sku };
                const isOpen = expanded.has(String(product.product_id));
                return [
                  <TableRow key={product.product_id} className={product.falta_demandas > 0 ? 'border-l-2 border-l-red-600' : 'border-l-2 border-l-transparent'}>
                    <TableCell className="px-3 py-2">
                      <div className="flex items-start gap-1.5">
                        <button type="button" onClick={() => toggleExpanded(product.product_id)} aria-expanded={isOpen}
                          aria-label={`${isOpen ? 'Ocultar' : 'Ver'} ${product.demandas.length} item(ns) de demanda de ${product.name}`}
                          className="mt-0.5 shrink-0 rounded text-muted-foreground hover:text-foreground disabled:opacity-30" disabled={product.demandas.length === 0}>
                          <ChevronRight className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                        </button>
                        <div className="min-w-0">
                          <Link className="block truncate text-base font-semibold leading-tight hover:text-blue-700 hover:underline" to={`/produtos/${product.product_id}/editar`}>{product.name}</Link>
                          <p className="truncate text-xs text-muted-foreground">{product.sku || 'Sem SKU'} · {product.demandas.length} demanda(s)</p>
                        </div>
                      </div>
                    </TableCell>
                    {COLUMNS.map((column) => <TableCell key={column.key} className={`px-2 py-2 text-right text-sm tabular-nums ${column.highlight && product[column.key] > 0 ? `font-semibold ${column.highlight}` : column.muted ? 'text-muted-foreground' : ''}`}>{number(product[column.key])}</TableCell>)}
                    <TableCell className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Input aria-label={`Quantidade para ${product.name}`} type="number" min="1" className="h-8 w-16" placeholder="Qtd" value={inputs[product.product_id] || ''} onChange={(event) => onInputChange(product.product_id, event.target.value)} />
                        <Button size="icon" variant="outline" className="h-8 w-8" title="Registrar entrada" aria-label={`Registrar entrada de ${product.name}`} onClick={() => onProduction(product.product_id)}><Plus className="h-4 w-4" /></Button>
                        <Button size="icon" variant="outline" className="h-8 w-8" title="Reservar / registrar saída" aria-label={`Reservar ou registrar saída de ${product.name}`} onClick={() => onRemoval(stockProduct)}><Minus className="h-4 w-4" /></Button>
                        <Button size="icon" variant="ghost" className="h-8 w-8" title="Histórico" aria-label={`Histórico de ${product.name}`} onClick={() => onLog(stockProduct)}><History className="h-4 w-4" /></Button>
                      </div>
                    </TableCell>
                  </TableRow>,
                  isOpen && <TableRow key={`${product.product_id}-detalhes`} className="bg-muted/20 hover:bg-muted/20">
                    <TableCell colSpan={COLUMNS.length + 2} className="px-3 py-2">
                      <p className="mb-2 text-xs text-muted-foreground">Mínimo: {number(product.estoque_minimo)} · Hoje: +{number(stockProduct.quantity_produced_today)} / −{number(stockProduct.quantity_removed_today)}</p>
                      <div className="space-y-1">{product.demandas.map((row) => <div key={`${row.demanda_id}-${row.item_id}`} className="flex flex-wrap justify-between gap-2 rounded-md bg-background p-2 text-sm">
                        <span><Link className="font-medium hover:underline" to={demandPath(row)}>{row.demanda_nome}</Link><SimulationBadge show={row.simulacao} /><span className="ml-2 text-muted-foreground">{date(row.data_entrega)}</span><span className="block text-xs text-muted-foreground">{row.item_nome}</span></span>
                        <span className="tabular-nums">Pendente {number(row.pendente)} · Estoque {number(row.coberto_estoque)} · <strong className="text-red-700">Falta {number(row.falta_apos_estoque)}</strong></span>
                      </div>)}</div>
                    </TableCell>
                  </TableRow>,
                ];
              })}
            </TableBody>
          </Table>
        </div>}
    </div> : view === 'demanda' ? <div className="space-y-2" role="tabpanel">
      {visibleDemands.length === 0 && <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhuma demanda encontrada nesta etapa.</div>}
      {visibleDemands.map((demand) => <Card key={demand.id}><CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><Link className="text-base font-semibold leading-tight hover:text-blue-700 hover:underline" to={demandPath(demand)}>{demand.name}</Link><SimulationBadge show={demand.simulacao} /><p className="text-xs text-muted-foreground">Entrega: {date(demand.deadline)} · Prioridade: {number(demand.priority)}</p></div><Badge variant={demand.unmapped.length > 0 ? 'outline' : demand.shortage > 0 ? 'destructive' : 'secondary'}>{demand.unmapped.length > 0 ? 'Mapeamento pendente' : demand.shortage > 0 ? `Faltam ${number(demand.shortage)}` : 'Coberta pelo estoque'}</Badge></div>
        <p className="text-sm tabular-nums">Pendente: <strong>{number(demand.pending)}</strong> {stage} · Coberto: <strong>{number(demand.covered)}</strong> · Falta: <strong className="text-red-700">{number(demand.shortage)}</strong></p>
        {demand.unmapped.length > 0 && <p className="text-xs text-amber-800">Totais parciais: itens sem vínculo confiável foram excluídos do cálculo.</p>}
        <div className="space-y-1">{demand.rows.map((row) => <div key={`${row.item_id}-${row.product_id}`} className="rounded-md border p-2 text-sm sm:flex sm:justify-between sm:gap-3"><div><span className="text-base font-semibold leading-tight">{row.product_name}</span><span className="ml-2 text-xs text-muted-foreground">{row.sku}</span><p className="text-xs text-muted-foreground">{row.item_nome} · {number(row.fator)} por unidade</p></div><div className="tabular-nums sm:text-right">Pendente {number(row.pendente)} · Estoque {number(row.coberto_estoque)} · <strong className="text-red-700">Falta {number(row.falta_apos_estoque)}</strong></div></div>)}
          {demand.unmapped.map((row) => <div key={row.item_id} className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">{row.item_nome}: {row.motivo}</div>)}
        </div>
      </CardContent></Card>)}
    </div> : view === 'grade' ? <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" role="tabpanel">
      {visibleProducts.length === 0
        ? <div className="col-span-full rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhum produto encontrado nesta etapa.</div>
        : visibleProducts.map((product) => {
          const stockProduct = stockById.get(String(product.product_id)) || { id: product.product_id, name: product.name, sku: product.sku };
          return <Card key={product.product_id} className={`flex flex-col ${product.falta_demandas > 0 ? 'border-l-4 border-l-red-600' : ''}`}>
            <CardContent className="flex flex-col gap-3 p-3">
              <div className="min-w-0">
                <Link className="block truncate text-sm font-semibold leading-tight hover:text-blue-700 hover:underline" to={`/produtos/${product.product_id}/editar`}>{product.name}</Link>
                <p className="truncate text-xs text-muted-foreground">{product.sku || 'Sem SKU'} · {product.demandas.length} demanda(s)</p>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                <span className="text-muted-foreground">Disponível</span><span className="text-right tabular-nums font-medium">{number(product.estoque_disponivel)}</span>
                <span className="text-muted-foreground">Pendente</span><span className="text-right tabular-nums font-medium">{number(product.demanda_pendente)}</span>
                {product.falta_demandas > 0 && <><span className="text-red-700">Falta</span><span className="text-right tabular-nums font-semibold text-red-700">{number(product.falta_demandas)}</span></>}
                {product.reposicao_minimo > 0 && <><span className="text-amber-700">Repor</span><span className="text-right tabular-nums font-semibold text-amber-700">{number(product.reposicao_minimo)}</span></>}
              </div>
              <p className="text-[10px] text-muted-foreground">Hoje: +{number(stockProduct.quantity_produced_today)} / −{number(stockProduct.quantity_removed_today)}</p>
              <div className="flex items-center gap-1 mt-auto">
                <Input aria-label={`Quantidade para ${product.name}`} type="number" min="1" className="h-8 flex-1 min-w-0" placeholder="Qtd" value={inputs[product.product_id] || ''} onChange={(event) => onInputChange(product.product_id, event.target.value)} />
                <Button size="icon" variant="outline" className="h-8 w-8 shrink-0" title="Registrar entrada" aria-label={`Registrar entrada de ${product.name}`} onClick={() => onProduction(product.product_id)}><Plus className="h-4 w-4" /></Button>
                <Button size="icon" variant="outline" className="h-8 w-8 shrink-0" title="Reservar / registrar saída" aria-label={`Reservar ou registrar saída de ${product.name}`} onClick={() => onRemoval(stockProduct)}><Minus className="h-4 w-4" /></Button>
                <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0" title="Histórico" aria-label={`Histórico de ${product.name}`} onClick={() => onLog(stockProduct)}><History className="h-4 w-4" /></Button>
              </div>
            </CardContent>
          </Card>;
        })}
    </div> : emPrevisao && previsao ? <PrevisaoMiolosTorre {...previsao} filter={filter} /> : null}
  </div>;
}
