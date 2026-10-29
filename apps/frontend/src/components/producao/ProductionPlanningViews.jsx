import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AlertTriangle, History, Loader2, Minus, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { dataCurta as date, numero as number } from '@/lib/formatoProducao';
import { agruparMiolosNaoMapeados, normalizarChaveMiolo } from '@/lib/miolosNaoMapeados';
import PrevisaoMiolosTorre from './PrevisaoMiolosTorre';

const demandPath = (row) => `/producao/${row.simulacao ? 'simulacao' : 'demanda'}/${row.demanda_id ?? row.id}/dashboard`;
const priorityName = (row) => row.trilha || (Number(row.prioridade) >= 100 ? 'Urgente' : Number(row.prioridade) > 0 ? 'Prioritária' : 'Normal');

export default function ProductionPlanningViews({ tipo, capaSubTab, setCapaSubTab, view, setView, planning, loading, error,
  products, filter, setFilter, inputs, onInputChange, onProduction, onRemoval, onLog, onRefresh,
  includeSimulations, setIncludeSimulations, previsao, horizonte, setHorizonte }) {
  const [merges, setMerges] = useState({});
  const [dragging, setDragging] = useState(null);
  const [allocationInputs, setAllocationInputs] = useState({});
  const stage = tipo === 'miolo' ? 'miolos' : capaSubTab === 'impressas' ? 'capas impressas' : 'capas acabadas';
  const rows = planning?.products || [];
  const unknown = tipo === 'miolo' ? agruparMiolosNaoMapeados(planning?.unmapped || []) :
    (planning?.unmapped || []).map((r, i) => ({ key: `${r.demanda_id}:${r.item_id ?? i}`, demanda_id: r.demanda_id, demanda_nome: r.demanda_nome,
      simulacao: r.simulacao, miolo_nome: r.miolo_nome || (tipo === 'miolo' ? null : r.item_nome), pendente: Number(r.pendente) || 0, rows: [r], quantidade_linhas: 1,
      data_entrega: r.data_entrega, prioridade: r.prioridade, horario_coleta: r.horario_coleta }));
  const productsById = useMemo(() => new Map(rows.map((p) => [String(p.product_id), p])), [rows]);
  const normalized = (s) => normalizarChaveMiolo(s).toLocaleLowerCase('pt-BR');
  const displayRows = useMemo(() => {
    const mergedKeys = new Set(Object.values(merges).flat());
    const mapped = rows.map((p) => ({ key: `id:${p.product_id}`, product: p, name: p.name, sku: p.sku, pending: p.demanda_pendente,
      covered: p.coberto_estoque, shortage: p.falta_demandas, demands: p.demandas, unmapped: false }));
    const buckets = new Map();
    for (const g of unknown) {
      if (mergedKeys.has(g.key)) continue;
      const normalizedName = normalized(g.miolo_nome);
      const key = normalizedName ? `text:${normalizedName}` : `line:${g.key}`;
      const bucket = buckets.get(key) || { key, name: g.miolo_nome || 'Miolo não identificado', pending: 0, demands: [], keys: [], unmapped: true };
      bucket.pending += g.pendente; bucket.keys.push(g.key); bucket.demands.push({ ...g, pendente: g.pendente }); buckets.set(key, bucket);
    }
    for (const [name, keys] of Object.entries(merges)) {
      const dest = productsById.get(name); if (!dest) continue;
      const groups = unknown.filter((g) => keys.includes(g.key));
      const pending = groups.reduce((n, g) => n + g.pendente, 0);
      mapped.find((r) => String(r.product.product_id) === name).pending += pending;
      // Recompute product stock coverage across the existing demand order, once.
      const row = mapped.find((r) => String(r.product.product_id) === name);
      // A mesma demanda pode ter várias linhas sem vínculo que foram
      // mescladas uma a uma. Consolide-as no componente de destino em vez de
      // renderizar uma linha adicional para cada origem.
      const demandMap = new Map();
      for (const d of row.demands || []) {
        const key = String(d.demanda_id);
        const current = demandMap.get(key);
        if (current) current.pendente += Number(d.pendente) || 0;
        else demandMap.set(key, { ...d, pendente: Number(d.pendente) || 0 });
      }
      for (const g of groups) {
        const key = String(g.demanda_id);
        const current = demandMap.get(key);
        if (current) {
          current.pendente += Number(g.pendente) || 0;
          current.manual_merge = true;
          current.miolo_nome = g.miolo_nome || current.miolo_nome;
        } else demandMap.set(key, { demanda_id: g.demanda_id, demanda_nome: g.demanda_nome, data_entrega: g.data_entrega,
          horario_coleta: g.horario_coleta, prioridade: g.prioridade, simulacao: g.simulacao, pendente: Number(g.pendente) || 0,
          miolo_nome: g.miolo_nome, manual_merge: true });
      }
      const demandRows = [...demandMap.values()];
      demandRows.sort((a, b) => (a.data_entrega || '9999').localeCompare(b.data_entrega || '9999') || Number(b.prioridade || 0) - Number(a.prioridade || 0));
      let stock = Number(dest.estoque_disponivel) || 0;
      for (const d of demandRows) { d.coberto_estoque = Math.min(stock, Number(d.pendente) || 0); d.falta_apos_estoque = d.pendente - d.coberto_estoque; stock -= d.coberto_estoque; }
      row.demands = demandRows; row.covered = demandRows.reduce((n, d) => n + d.coberto_estoque, 0); row.shortage = demandRows.reduce((n, d) => n + d.falta_apos_estoque, 0);
      row.manualSources = groups;
    }
    return [...mapped, ...buckets.values()];
  }, [rows, unknown, merges, productsById]);
  const query = filter.trim().toLocaleLowerCase('pt-BR');
  const visibleRows = displayRows.filter((r) => !query || [r.name, r.sku, ...(r.demands || []).map((d) => d.demanda_nome)].some((v) => String(v || '').toLocaleLowerCase('pt-BR').includes(query)));
  const byDemand = new Map();
  for (const row of displayRows) for (const d of row.demands || []) {
    const id = String(d.demanda_id); const demand = byDemand.get(id) || { id, name: d.demanda_nome, deadline: d.data_entrega, collection: d.horario_coleta,
      priority: d.prioridade, simulation: d.simulacao, components: [], pending: 0, covered: 0, shortage: 0 };
    demand.components.push({ ...d, name: row.name, sku: row.sku, unmapped: row.unmapped, manual: d.manual_merge,
      sourceKey: row.unmapped ? d.key : null, productId: row.product?.product_id });
    demand.pending += Number(d.pendente) || 0; demand.covered += Number(d.coberto_estoque) || 0;
    demand.shortage += row.unmapped ? Number(d.pendente) || 0 : Number(d.falta_apos_estoque) || 0; byDemand.set(id, demand);
  }
  if (tipo === 'miolo') {
    for (const demand of byDemand.values()) {
      const totals = new Map();
      for (const component of demand.components) {
        const label = component.name || component.miolo_nome || 'Miolo não identificado';
        const key = normalized(label);
        const current = totals.get(key);
        if (!current) {
          totals.set(key, { ...component, name: label, pending: Number(component.pendente) || 0,
            covered: Number(component.coberto_estoque) || 0,
            shortage: component.unmapped ? Number(component.pendente) || 0 : Number(component.falta_apos_estoque) || 0,
            hasUnmapped: Boolean(component.unmapped), productIds: component.productId ? [String(component.productId)] : [], manual: Boolean(component.manual) });
        } else {
          current.pending += Number(component.pendente) || 0;
          current.covered += Number(component.coberto_estoque) || 0;
          current.shortage += component.unmapped ? Number(component.pendente) || 0 : Number(component.falta_apos_estoque) || 0;
          current.hasUnmapped ||= Boolean(component.unmapped);
          if (component.productId && !current.productIds.includes(String(component.productId))) current.productIds.push(String(component.productId));
          current.manual ||= Boolean(component.manual);
        }
      }
      demand.components = [...totals.values()];
    }
  }
  const demands = [...byDemand.values()].filter((d) => !query || [d.name, ...d.components.map((c) => c.name)].some((v) => String(v || '').toLocaleLowerCase('pt-BR').includes(query)))
    .sort((a,b) => (a.deadline || '9999').localeCompare(b.deadline || '9999') || Number(b.priority || 0) - Number(a.priority || 0) || (a.collection || '23:59').localeCompare(b.collection || '23:59'));
  const total = visibleRows.reduce((s, r) => ({ need: s.need + (Number(r.pending) || 0), shortage: s.shortage + (Number(r.shortage) || 0) }), { need: 0, shortage: 0 });
  const choices = [{ key: 'atrasado', label: 'Hoje' }, { key: 'amanha', label: 'Amanhã' }, { key: 'depois', label: 'Próximos dias' }];
  const viewLabels = [['demanda','Demandas'],['produto','Estoque'],['previsao','Previsão da Torre']];
  const mergeOne = (groupKey, productId) => {
    setMerges((current) => {
      const next = Object.fromEntries(Object.entries(current).map(([id, keys]) => [id, keys.filter((key) => key !== groupKey)]).filter(([, keys]) => keys.length));
      next[String(productId)] = [...(next[String(productId)] || []), groupKey];
      return next;
    });
    setDragging(null);
  };
  const unmerge = (id) => setMerges((m) => { const n = { ...m }; delete n[id]; return n; });

  return <main className="space-y-4">
    <header><h1 className="text-2xl font-bold">Produção de {tipo === 'miolo' ? 'miolos' : 'capas'}</h1><p className="text-sm text-muted-foreground">{loading ? 'Atualizando planejamento…' : `${number(total.need)} ${stage} necessários · ${number(total.shortage)} para produzir`}</p></header>
    <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
      {tipo === 'capa' && <div className="flex gap-1" role="group" aria-label="Etapa das capas">{[['impressas','Impressão'],['acabadas','Acabamento']].map(([k,l]) => <Button key={k} size="sm" variant={capaSubTab===k?'default':'outline'} onClick={() => setCapaSubTab(k)}>{l}</Button>)}</div>}
      <div className="flex gap-1" role="tablist" aria-label="Visão de produção">{viewLabels.map(([k,l]) => <Button key={k} size="sm" role="tab" aria-selected={view===k} variant={view===k?'default':'outline'} onClick={() => setView(k)}>{l}</Button>)}</div>
      {view === 'previsao' && <div className="flex gap-1">{choices.map((c) => <Button key={c.key} size="sm" variant={horizonte?.includes(c.key)?'secondary':'outline'} onClick={() => setHorizonte?.(horizonte?.includes(c.key)?horizonte.filter((x)=>x!==c.key):[...(horizonte||[]),c.key])}>{c.label}</Button>)}</div>}
      <div className="relative ml-auto min-w-48 flex-1 sm:max-w-xs"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground"/><Input className="h-9 pl-8" placeholder="Buscar componente ou demanda" value={filter} onChange={(e)=>setFilter(e.target.value)}/></div>
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={includeSimulations} onChange={(e)=>setIncludeSimulations(e.target.checked)}/> Simulações</label>
      <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading}>Atualizar</Button>
    </div>
    {error && <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-red-900">{error}</p>}
    {unknown.length > 0 && view !== 'previsao' && <p className="flex items-center gap-2 text-sm text-amber-800"><AlertTriangle className="h-4 w-4"/> Mesclar: arraste cada linha sem vínculo para o miolo cadastrado correspondente. Clique em “Desfazer” para reverter.</p>}
    {view === 'previsao' ? <PrevisaoMiolosTorre {...(previsao || {})} filter={filter} /> : view === 'demanda' ? <section className="space-y-3">{demands.map((d)=><Card key={d.id}><CardContent className="space-y-3 p-4"><header className="flex flex-wrap justify-between gap-2"><div><Link className="font-semibold hover:underline" to={demandPath({id:d.id,simulacao:d.simulation})}>{d.name}</Link><p className="text-xs text-muted-foreground">Prazo {date(d.deadline,'Sem prazo')} · Coleta {d.collection || '—'} · {priorityName(d)}</p></div><Badge variant={d.shortage?'destructive':'secondary'}>{d.shortage?`${number(d.shortage)} para produzir`:'Coberta pelo estoque'}</Badge></header><div className="grid grid-cols-[minmax(0,1fr)_110px_80px_100px_150px] gap-x-3 border-b pb-1 text-xs font-medium text-muted-foreground"><span>{tipo==='miolo'?'Miolo':'Capa'}</span><span className="text-right">Necessidade</span><span className="text-right">Estoque</span><span className="text-right">Produzir</span><span className="text-right">Alocar</span></div>{d.components.map((c,i)=><div key={`${c.item_id}-${i}`} draggable={!!c.unmapped} onDragStart={(e)=>{if(!c.unmapped)return;setDragging(c.sourceKey);e.dataTransfer.setData('text/plain',c.sourceKey);e.dataTransfer.effectAllowed='move';}} onDragEnd={()=>setDragging(null)} onDragOver={(e)=>!c.unmapped&&e.preventDefault()} onDrop={(e)=>{e.preventDefault();const key=e.dataTransfer.getData('text/plain')||dragging;if(key&&!c.unmapped)mergeOne(key,c.productId);}} className={`grid grid-cols-[minmax(0,1fr)_110px_80px_100px_150px] items-center gap-x-3 border-b py-2 text-sm ${c.unmapped?'cursor-grab':'border-transparent'} ${dragging&&!c.unmapped?'bg-primary/5':''}`}><span className="truncate">{c.name} {c.hasUnmapped&&<Badge variant="outline">Estoque não confirmado</Badge>}{c.manual&&<Badge variant="secondary">Mesclado</Badge>} {c.manual&&<Button size="sm" variant="ghost" onClick={()=>unmerge(String(c.productId))}>Desfazer</Button>}</span><span className="text-right tabular-nums">{number(c.pending)}</span><span className="text-right tabular-nums">{c.hasUnmapped?'—':number(c.covered)}</span><strong className="text-right tabular-nums">{c.hasUnmapped?`${number(c.shortage)} · conferir`:number(c.shortage)}</strong><div className="flex justify-end gap-1">{tipo==='miolo'&&c.productId&&c.productIds?.length===1&&!c.hasUnmapped&&c.pending>0&&(()=>{const product=products.find((p)=>String(p.id)===String(c.productId));const available=Number(product?.stock_details?.quantidade_disponivel??product?.quantidade_disponivel??0);const maxAlloc=Math.min(Number(c.pending)||0,available);const key=`${d.id}:${c.productId}`;return product&&maxAlloc>0&&<><Input aria-label={`Quantidade de miolos para alocar em ${d.name}`} className='h-8 w-16' type='number' min='0.0001' max={maxAlloc} step='any' value={allocationInputs[key]??String(maxAlloc)} onChange={(e)=>setAllocationInputs((v)=>({...v,[key]:e.target.value}))}/><Button size='sm' variant='outline' onClick={()=>onRemoval(product,{demandaId:d.id,quantity:Number(allocationInputs[key]??maxAlloc),maxQuantity:c.pending})}>Alocar</Button></>})()}</div></div>)}</CardContent></Card>)}{!demands.length&&<p className="rounded border border-dashed p-8 text-center">Nenhuma demanda neste recorte.</p>}</section> : <section className="space-y-2">{visibleRows.map((r)=><Card key={r.key} onDragOver={(e)=>!r.unmapped&&e.preventDefault()} onDrop={(e)=>{e.preventDefault(); const key=e.dataTransfer.getData('text/plain')||dragging; if(key&&!r.unmapped)mergeOne(key,r.product.product_id);}} className={dragging&&!r.unmapped?'border-primary bg-primary/5':''}><CardContent className="flex flex-wrap items-center gap-4 p-3"><div className="min-w-48 flex-1"><strong>{r.name}</strong><p className="text-xs text-muted-foreground">{r.unmapped?'Estoque não confirmado':r.sku} · {r.demands?.length||0} demanda(s)</p>{r.unmapped&&<div className="mt-1 flex flex-wrap gap-1">{r.keys.map((k)=><span key={k} draggable onDragStart={(e)=>{e.stopPropagation();setDragging(k);e.dataTransfer.setData('text/plain',k);e.dataTransfer.effectAllowed='move';}} onDragEnd={()=>setDragging(null)} className="cursor-grab rounded border bg-background px-2 py-1 text-xs">Arraste esta linha · {unknown.find((g)=>g.key===k)?.demanda_nome}</span>)}</div>}</div><div className="text-right"><small className="block text-muted-foreground">Disponível</small>{r.unmapped?'—':number(r.product.estoque_disponivel)}</div><div className="text-right"><small className="block text-muted-foreground">Necessidade</small>{number(r.pending)}</div><strong className="text-right">{r.unmapped?`${number(r.pending)} a conferir`:number(r.shortage)}<small className="block text-muted-foreground">{r.unmapped?'A conferir':'A produzir'}</small></strong>{!r.unmapped&&<><Input aria-label={`Quantidade ${r.name}`} type="number" min="1" className="h-8 w-20" value={inputs[r.product.product_id]||''} onChange={(e)=>onInputChange(r.product.product_id,e.target.value)}/><Button size="sm" onClick={()=>onProduction(r.product.product_id)}><Plus className="mr-1 h-4 w-4"/>Produzir</Button><Button size="sm" variant="outline" onClick={()=>onRemoval(r.product)}><Minus className="mr-1 h-4 w-4"/>Alocar</Button><Button size="icon" variant="ghost" aria-label={`Histórico ${r.name}`} onClick={()=>onLog(r.product)}><History className="h-4 w-4"/></Button></>}</CardContent></Card>)}{!visibleRows.length&&<p className="rounded border border-dashed p-8 text-center">Nenhum componente neste recorte.</p>}</section>}
  </main>;
}
