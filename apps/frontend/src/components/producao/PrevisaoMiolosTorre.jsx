import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { abaDoBucketPrazo, alternarPrazo, urlDoEscopo } from '@/lib/escopoDespacho';
import { dataCurta, numero } from '@/lib/formatoProducao';
import { AlertTriangle, ChevronRight, FileText, Loader2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

const HORIZONTES = [
  { key: 'atrasado', label: 'Atrasado' },
  { key: 'hoje', label: 'Hoje' },
  { key: 'amanha', label: 'Amanhã' },
  { key: 'sem_prazo', label: 'Sem prazo' },
  { key: 'depois', label: 'Depois' },
];
const BUCKET_LABEL = Object.fromEntries(HORIZONTES.map(({ key, label }) => [key, label]));

const normaliza = (value) => String(value || '').toLocaleLowerCase('pt-BR');
const dataPrevista = (lote) => lote.bucket === 'atrasado' ? 'Vencido' : dataCurta(lote.data_limite_dia, 'Sem prazo');

function Toggle({ pressed, onClick, children }) {
  return <Button size="sm" variant={pressed ? 'default' : 'outline'} aria-pressed={pressed} onClick={onClick}>{children}</Button>;
}

export default function PrevisaoMiolosTorre({ data, loading, error, filtros, onChangeFiltros, onRefresh, filter }) {
  const [recorte, setRecorte] = useState('miolo');
  const [expanded, setExpanded] = useState(() => new Set());
  const toggleExpanded = (id) => setExpanded((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });

  const query = normaliza(filter).trim();
  const resumo = data?.resumo;
  const miolos = useMemo(() => (data?.miolos || []).filter((miolo) => !query
    || [miolo.nome, miolo.sku, ...miolo.por_lote.map((l) => `${l.nome_marketplace} ${l.nome_modalidade}`)]
      .some((value) => normaliza(value).includes(query))), [data, query]);
  const lotes = useMemo(() => (data?.lotes || []).filter((lote) => !query
    || [lote.nome_marketplace, lote.nome_modalidade, ...lote.miolos.map((m) => m.miolo_nome)]
      .some((value) => normaliza(value).includes(query))), [data, query]);
  const porPlataforma = useMemo(() => {
    const grupos = new Map();
    for (const lote of lotes) {
      const chave = String(lote.integration_id ?? 'sem');
      if (!grupos.has(chave)) grupos.set(chave, { nome: lote.nome_marketplace, lotes: [], pedidos: 0, miolos: 0 });
      const grupo = grupos.get(chave);
      grupo.lotes.push(lote);
      grupo.pedidos += lote.qtd_pedidos || 0;
      grupo.miolos += lote.total_miolos || 0;
    }
    return [...grupos.values()];
  }, [lotes]);
  const semMiolo = (data?.lotes || []).filter((lote) => lote.sem_miolo.length > 0);

  return <div className="space-y-3" role="tabpanel">
    <p className="text-xs text-muted-foreground">Projeção dos lotes ainda não publicados na Torre de Despacho. Nada é reservado; ao publicar, o lote sai daqui e passa a contar em “Demanda pendente”.</p>

    <div className="flex flex-wrap items-center gap-2">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Prazo dos lotes">
        {HORIZONTES.map(({ key, label }) => <Toggle key={key} pressed={filtros.horizonte.includes(key)}
          onClick={() => onChangeFiltros({ ...filtros, horizonte: alternarPrazo(filtros.horizonte, key) })}>{label}</Toggle>)}
      </div>
      <div className="h-5 w-px bg-border" />
      <label className="flex items-center gap-2 whitespace-nowrap text-sm text-muted-foreground">
        <input type="checkbox" className="h-4 w-4 rounded border-input accent-primary" checked={filtros.incluirPronto}
          onChange={(event) => onChangeFiltros({ ...filtros, incluirPronto: event.target.checked })} />
        Incluir “Pronto para envio”
      </label>
      <div className="h-5 w-px bg-border" />
      <div className="flex gap-1" role="group" aria-label="Agrupar por">
        <Toggle pressed={recorte === 'miolo'} onClick={() => setRecorte('miolo')}>Por miolo</Toggle>
        <Toggle pressed={recorte === 'lote'} onClick={() => setRecorte('lote')}>Por lote</Toggle>
      </div>
    </div>

    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      {error} <button type="button" className="underline" onClick={onRefresh}>Tentar novamente</button>
    </div>}
    {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Consolidando os lotes da Torre…</div>}

    {resumo && <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm">
      <span className="text-muted-foreground">Miolos previstos <strong className="ml-1 text-base tabular-nums text-foreground">{numero(resumo.total_miolos)}</strong></span>
      <span className="text-muted-foreground">Falta após estoque <strong className="ml-1 text-base tabular-nums text-red-700">{numero(resumo.total_falta)}</strong></span>
      <span className="text-muted-foreground">Lotes <strong className="ml-1 tabular-nums text-foreground">{numero(resumo.total_lotes)}</strong></span>
      <span className="text-muted-foreground">Pedidos <strong className="ml-1 tabular-nums text-foreground">{numero(resumo.total_pedidos)}</strong></span>
      <span className="text-xs text-muted-foreground">{miolos.length} de {resumo.miolos_distintos} miolos</span>
    </div>}

    {data?.truncado && <div role="alert" className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
      <AlertTriangle className="h-4 w-4 shrink-0" /> Há {data.total_lotes_pendentes} lotes no recorte; os totais abaixo cobrem só os primeiros {data.lotes.length}, por ordem de saída. Reduza os prazos para ver o restante.
    </div>}
    {semMiolo.length > 0 && <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
      <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> {resumo.linhas_sem_miolo} linha(s) sem miolo identificado — não entram nos totais</div>
      <details className="mt-1"><summary className="cursor-pointer text-xs font-medium">Ver linhas afetadas</summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">{semMiolo.flatMap((lote) => lote.sem_miolo.map((linha, index) => <li key={`${lote.lote_chave}-${lote.data_limite_dia}-${index}`}>
          {lote.nome_marketplace} · {lote.nome_modalidade}: {linha.descricao} ({numero(linha.quantidade)}) — {linha.motivo}</li>))}</ul>
      </details>
    </div>}

    {data && recorte === 'miolo' && (miolos.length === 0
      ? <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhum lote pendente neste recorte.</div>
      : <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background shadow-[inset_0_-1px_0_hsl(var(--border))]">
            <TableRow>
              <TableHead className="h-9 w-[50%] min-w-[220px] px-3">Miolo</TableHead>
              <TableHead className="h-9 w-[80px] px-2 text-right text-xs" title="Estoque disponível">Disp.</TableHead>
              <TableHead className="h-9 w-[80px] px-2 text-right text-xs" title="Quantidade prevista pelos lotes">Previsto</TableHead>
              <TableHead className="h-9 w-[80px] px-2 text-right text-xs" title="Previsto menos estoque disponível">Falta</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {miolos.flatMap((miolo) => {
              const isOpen = expanded.has(miolo.miolo_key);
              return [
                <TableRow key={miolo.miolo_key} className={miolo.falta > 0 ? 'border-l-2 border-l-red-600' : 'border-l-2 border-l-transparent'}>
                  <TableCell className="px-3 py-2">
                    <div className="flex items-start gap-1.5">
                      <button type="button" onClick={() => toggleExpanded(miolo.miolo_key)} aria-expanded={isOpen}
                        aria-label={`${isOpen ? 'Ocultar' : 'Ver'} lotes de ${miolo.nome}`} className="mt-0.5 shrink-0 rounded text-muted-foreground hover:text-foreground">
                        <ChevronRight className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                      </button>
                      <div className="min-w-0">
                        {miolo.id_produto_miolo
                          ? <Link className="block truncate text-base font-semibold leading-tight hover:text-blue-700 hover:underline" to={`/produtos/${miolo.id_produto_miolo}/editar`}>{miolo.nome}</Link>
                          : <span className="block truncate text-base font-semibold leading-tight">{miolo.nome}</span>}
                        <p className="truncate text-xs text-muted-foreground">
                          {miolo.sku || (miolo.sem_estoque_cadastrado ? 'Sem cadastro de estoque' : 'Sem SKU')} · {miolo.por_lote.length} lote(s)
                        </p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="px-2 py-2 text-right text-sm tabular-nums text-muted-foreground">{miolo.estoque_disponivel === null ? '—' : numero(miolo.estoque_disponivel)}</TableCell>
                  <TableCell className="px-2 py-2 text-right text-sm tabular-nums">{numero(miolo.quantidade_total)}</TableCell>
                  <TableCell className={`px-2 py-2 text-right text-sm tabular-nums ${miolo.falta > 0 ? 'font-semibold text-red-700' : 'text-muted-foreground'}`}>{numero(miolo.falta)}</TableCell>
                </TableRow>,
                isOpen && <TableRow key={`${miolo.miolo_key}-lotes`} className="bg-muted/20 hover:bg-muted/20">
                  <TableCell colSpan={4} className="px-3 py-2">
                    <div className="space-y-1">{miolo.por_lote.map((lote, index) => <div key={`${lote.lote_chave}-${lote.data_limite_dia}-${index}`} className="flex flex-wrap justify-between gap-2 rounded-md bg-background p-2 text-sm">
                      <span><span className="font-medium">{lote.nome_marketplace}</span> · {lote.nome_modalidade}
                        <span className="ml-2 text-muted-foreground">{dataPrevista(lote)}</span></span>
                      <span className="tabular-nums">{numero(lote.quantidade)}</span>
                    </div>)}</div>
                  </TableCell>
                </TableRow>,
              ];
            })}
          </TableBody>
        </Table>
      </div>)}

    {data && recorte === 'lote' && (porPlataforma.length === 0
      ? <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">Nenhum lote pendente neste recorte.</div>
      : porPlataforma.map((grupo) => <section key={grupo.nome} className="overflow-hidden rounded-lg border">
        <header className="flex flex-wrap items-baseline justify-between gap-2 border-b bg-muted/30 px-3 py-2">
          <h2 className="text-base font-semibold leading-tight">{grupo.nome}</h2>
          <span className="text-xs tabular-nums text-muted-foreground">{numero(grupo.pedidos)} pedidos · {numero(grupo.miolos)} miolos</span>
        </header>
        <ul className="divide-y">{grupo.lotes.map((lote) => {
          const id = `${lote.integration_id}-${lote.lote_chave}-${lote.data_limite_dia || 'sem'}`;
          const isOpen = expanded.has(id);
          return <li key={id} className="px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-start gap-1.5">
                <button type="button" onClick={() => toggleExpanded(id)} aria-expanded={isOpen}
                  aria-label={`${isOpen ? 'Ocultar' : 'Ver'} miolos do lote ${lote.nome_modalidade}`} className="mt-0.5 shrink-0 rounded text-muted-foreground hover:text-foreground">
                  <ChevronRight className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                </button>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-semibold">{lote.nome_modalidade}</span>
                    <Badge variant={lote.bucket === 'atrasado' ? 'destructive' : 'outline'} className="h-5 px-1.5 text-[10px]">{BUCKET_LABEL[lote.bucket] || lote.bucket}</Badge>
                    {lote.rascunho && <Badge variant="secondary" className="h-5 gap-1 px-1.5 text-[10px]"><FileText className="h-3 w-3" /> consolidação aberta</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground">Envio até {dataPrevista(lote)}</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-right text-sm tabular-nums"><strong>{numero(lote.total_miolos)}</strong> <span className="text-xs text-muted-foreground">miolos · {numero(lote.qtd_pedidos)} pedidos</span></span>
                <Button asChild size="sm" variant="outline">
                  <Link to={urlDoEscopo({
                    integrationId: lote.integration_id, modalidadeIds: lote.modalidade_ids, nomeMarketplace: lote.nome_marketplace,
                    nomeModalidade: lote.nome_modalidade, aba: abaDoBucketPrazo(lote.bucket), incluirPronto: data.incluir_pronto,
                  })}>{lote.rascunho ? 'Continuar' : 'Conferir lote'}</Link>
                </Button>
              </div>
            </div>
            {isOpen && <div className="mt-2 space-y-1">{lote.miolos.length === 0
              ? <p className="rounded-md bg-muted/20 p-2 text-sm text-muted-foreground">Nenhum miolo identificado neste lote.</p>
              : lote.miolos.map((miolo) => <div key={miolo.miolo_key} className="flex justify-between gap-2 rounded-md bg-muted/20 p-2 text-sm">
                <span className="truncate">{miolo.miolo_nome}</span><span className="tabular-nums">{numero(miolo.quantidade)}</span>
              </div>)}</div>}
          </li>;
        })}</ul>
      </section>))}
  </div>;
}
