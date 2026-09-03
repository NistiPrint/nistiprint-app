import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import PacoteBadge from '@/components/pedidos/PacoteBadge';
import AcoesDoLote from '@/components/despacho/AcoesDoLote';
import ConferenciaDoArquivo from '@/components/despacho/ConferenciaDoArquivo';
import LinhasConsolidadas from '@/components/despacho/LinhasConsolidadas';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { prepararLinhasParaEnvio, totalizarLinhas, linhasParaTsv } from '@/lib/consolidacaoEditavel';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { AlertTriangle, ArrowLeft, ChevronRight, Copy, MoreHorizontal } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

const HORIZONTE_STEPS = ['atrasado', 'hoje', 'amanha', 'depois'];
const HORIZONTE_LABEL = { atrasado: 'Atrasado', hoje: 'Hoje', amanha: 'Amanhã', depois: 'Depois' };
const ABA_PARA_DEGRAU = { hoje: 1, amanha: 2, proximos: 3 };

function parseIntOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const numero = parseInt(value, 10);
  return Number.isNaN(numero) ? null : numero;
}

function PedidosAssociados({ pedidos = [] }) {
  const ids = pedidos.map((pedido) => pedido.marketplace_order_id || pedido.codigo_pedido_externo).filter(Boolean);
  const copiarIds = async () => {
    if (!ids.length) return;
    await navigator.clipboard.writeText(ids.join(';'));
    toast.success('IDs dos pedidos copiados.');
  };
  return (
    <Sheet>
      <SheetTrigger asChild><Button type="button" variant="outline" size="icon" aria-label="Mais ações"><MoreHorizontal className="h-4 w-4" /></Button></SheetTrigger>
      <SheetContent side="right" className="w-[96vw] overflow-y-auto sm:max-w-3xl">
        <SheetHeader><SheetTitle>Pedidos associados ({pedidos.length})</SheetTitle></SheetHeader>
        <Button type="button" variant="outline" size="sm" className="mt-5 gap-2" onClick={copiarIds}><Copy className="h-4 w-4" /> Copiar todos os IDs</Button>
        {ids.length > 0 && <div className="mt-3 rounded-md border bg-muted/30 p-3"><div className="mb-1 text-xs font-medium">IDs do Bling/marketplace</div><div className="break-all font-mono text-xs text-muted-foreground">{ids.join(';')}</div></div>}
        {pedidos.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">Nenhum pedido associado.</p> : <div className="mt-4 overflow-x-auto rounded-md border"><table className="w-full min-w-[680px] text-sm"><thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Pedido</th><th className="px-3 py-2">ID no marketplace</th><th className="px-3 py-2">Cliente</th><th className="px-3 py-2">Total</th><th className="px-3 py-2">Prazo</th><th className="px-3 py-2">Envio</th></tr></thead><tbody>{pedidos.map((pedido) => <tr key={pedido.id} className="border-t"><td className="px-3 py-2"><div className="flex items-center gap-2"><span>{pedido.numero_pedido || pedido.codigo_pedido_externo}</span><PacoteBadge variant="inline" irmaos={pedido.pack_irmaos} irmaosIds={pedido.pack_irmaos_ids} /></div></td><td className="px-3 py-2 font-mono text-xs">{pedido.marketplace_order_id || pedido.codigo_pedido_externo || '—'}</td><td className="px-3 py-2">{pedido.cliente_nome || '—'}</td><td className="px-3 py-2">{pedido.total_pedido == null ? '—' : Number(pedido.total_pedido).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</td><td className="px-3 py-2">{pedido.data_limite_envio ? new Date(pedido.data_limite_envio).toLocaleDateString('pt-BR') : 'não informado'}</td><td className="px-3 py-2">{pedido.metodo_envio_rotulo || 'não classificado'}</td></tr>)}</tbody></table></div>}
      </SheetContent>
    </Sheet>
  );
}

function PreviaConsolidacao({ params, onLinhasChange, onBaseline }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const chave = useMemo(() => { const query = new URLSearchParams(); Object.entries(params || {}).forEach(([nome, valor]) => { if (valor === null || valor === undefined || valor === '') return; if (Array.isArray(valor)) valor.forEach((item) => query.append(nome, item)); else query.set(nome, valor); }); return query.toString(); }, [params]);
  useEffect(() => {
    let vivo = true;
    setCarregando(true); setErro(null);
    (async () => { try { const resposta = await fetch(`/api/v2/despacho/previsao?${chave}`); const json = await resposta.json(); if (!json.success) throw new Error(json.error || 'Falha ao montar a consolidação'); if (vivo) { setDados(json.data); onBaseline?.(json.data); } } catch (err) { if (vivo) setErro(err.message); } finally { if (vivo) setCarregando(false); } })();
    return () => { vivo = false; };
  }, [chave, onBaseline]);
  return <LinhasConsolidadas key={`${chave}-${dados?.previsao_versao || 'loading'}`} itens={dados?.itens || []} resumo={dados} carregando={carregando} erro={erro} onChange={onLinhasChange} />;
}

export default function EscopoDespachoPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  useSecaoSidebar();
  const integrationId = parseIntOrNull(searchParams.get('integration_id'));
  const conferenciaId = parseIntOrNull(searchParams.get('conferencia_id'));
  const origemArquivo = conferenciaId !== null;
  const modalidadeIds = useMemo(() => { const lista = searchParams.getAll('modalidade_ids').map(parseIntOrNull).filter((valor) => valor !== null); if (lista.length) return lista; const unico = parseIntOrNull(searchParams.get('modalidade_id')); return unico === null ? [] : [unico]; }, [searchParams]);
  const marketplaceNome = searchParams.get('marketplace_nome') || 'Origem não resolvida';
  const modalidadeNome = searchParams.get('modalidade_nome') || 'Modalidade não classificada';
  const abaOrigem = searchParams.get('aba') || 'hoje';
  const [horizonteAte, setHorizonteAte] = useState(ABA_PARA_DEGRAU[abaOrigem] ?? 1);
  const [incluirSemPrazo, setIncluirSemPrazo] = useState(abaOrigem === 'hoje');
  const [dados, setDados] = useState(null);
  const [loading, setLoading] = useState(true);
  const [publicando, setPublicando] = useState(false);
  const [conflitos, setConflitos] = useState([]);
  const [erro, setErro] = useState(null);
  const [linhasEditadas, setLinhasEditadas] = useState([]);
  const [previsaoVersao, setPrevisaoVersao] = useState(null);
  const baselineRef = useRef('');
  const horizonte = useMemo(() => { const passos = HORIZONTE_STEPS.slice(0, horizonteAte + 1); return incluirSemPrazo ? [...passos, 'sem_prazo'] : passos; }, [horizonteAte, incluirSemPrazo]);
  const chaveDoEscopo = useMemo(() => origemArquivo ? { conferencia_id: conferenciaId } : { integration_id: integrationId ?? undefined, modalidade_ids: modalidadeIds, modalidade_id: modalidadeIds[0] ?? undefined, horizonte, data: dataOperacionalHoje() }, [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte]);
  const carregar = useCallback(async () => {
    setLoading(true); setErro(null);
    try { const params = new URLSearchParams(); if (origemArquivo) params.set('conferencia_id', conferenciaId); else { if (integrationId !== null) params.set('integration_id', integrationId); modalidadeIds.forEach((id) => params.append('modalidade_ids', id)); if (modalidadeIds.length) params.set('modalidade_id', modalidadeIds[0]); horizonte.forEach((item) => params.append('horizonte', item)); params.set('data', dataOperacionalHoje()); } const resposta = await fetch(`/api/v2/despacho/escopo?${params.toString()}`); const json = await resposta.json(); if (!json.success) throw new Error(json.error || 'Falha ao carregar o escopo'); setDados(json.data); } catch (err) { setErro(err.message || 'Não foi possível carregar o escopo.'); } finally { setLoading(false); }
  }, [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte]);
  useEffect(() => { carregar(); }, [carregar]);
  const publicar = async () => {
    setPublicando(true); setConflitos([]);
    try {
      const lancamento = await fetch('/api/v2/despacho/lancar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ integration_id: integrationId, modalidade_ids: modalidadeIds, modalidade_id: modalidadeIds[0] ?? null, horizonte, data: dataOperacionalHoje(), ...(origemArquivo ? { conferencia_id: conferenciaId } : {}), previsao_versao: previsaoVersao }) });
      const criado = await lancamento.json(); if (!criado.success) throw new Error(criado.error || 'Não foi possível montar a demanda');
      setConflitos(criado.data.ja_em_rascunho || []);
      const linhas = prepararLinhasParaEnvio(linhasEditadas);
      const publicado = await fetch('/api/v2/despacho/publicar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ demanda_id: criado.data.demanda_id, linhas, previsao_versao: previsaoVersao }) });
      const json = await publicado.json(); if (!json.success) throw new Error(json.error || 'Não foi possível publicar');
      toast.success(`${json.data.demanda_codigo} publicada — ${json.data.total_pedidos} pedidos foram para produção`); navigate('/despacho');
    } catch (err) { toast.error(err.message || 'Não foi possível publicar a demanda'); } finally { setPublicando(false); }
  };
  const copiar = async () => {
    try { await navigator.clipboard.writeText(linhasParaTsv(linhasEditadas)); toast.success('Tabela copiada para a planilha.'); }
    catch { toast.error('Não foi possível copiar a tabela.'); }
  };
  const total = dados?.total ?? 0;
  const totalItens = totalizarLinhas(linhasEditadas);
  const totalNo = dados?.total_no ?? total;
  const foraDoHorizonte = Math.max(0, totalNo - total);
  const qtdSemPrazo = dados?.buckets?.sem_prazo ?? 0;
  const onBaseline = useCallback((valor) => { setPrevisaoVersao(valor?.previsao_versao || null); setLinhasEditadas(valor?.itens || []); }, []);
  const temAlteracoes = baselineRef.current && JSON.stringify(linhasEditadas) !== baselineRef.current;
  const confirmarDescarte = useCallback(() => !temAlteracoes || window.confirm('Existem alterações não publicadas. Deseja descartá-las?'), [temAlteracoes]);
  const registrarBaseline = useCallback((valor) => { baselineRef.current = JSON.stringify(valor?.itens || []); onBaseline(valor); }, [onBaseline]);
  return <div className="p-6">
    <button type="button" onClick={() => confirmarDescarte() && navigate('/despacho')} className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Voltar para a torre de despacho</button>
    <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">{origemArquivo && <><span>📄 conferência de arquivo</span><ChevronRight className="h-3.5 w-3.5" /></>}<span>{marketplaceNome}</span><ChevronRight className="h-3.5 w-3.5" /><span className="font-medium text-foreground">{modalidadeNome}</span></div>
    {origemArquivo && <ConferenciaDoArquivo conferenciaId={conferenciaId} onMudou={carregar} />}
    {!origemArquivo && <Card className="mb-6"><CardContent className="py-5"><div className="mb-3 text-sm font-medium">Horizonte</div><div className="flex flex-wrap gap-2">{HORIZONTE_STEPS.map((step, indice) => <button key={step} type="button" onClick={() => confirmarDescarte() && setHorizonteAte(indice)} className={`rounded-full border px-3 py-1 text-xs ${indice <= horizonteAte ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>até {HORIZONTE_LABEL[step]} {dados?.buckets?.[step] ? <span className="ml-1.5 opacity-70">{dados.buckets[step]}</span> : null}</button>)}{qtdSemPrazo > 0 && <button type="button" onClick={() => confirmarDescarte() && setIncluirSemPrazo((valor) => !valor)} className={`rounded-full border px-3 py-1 text-xs ${incluirSemPrazo ? 'border-amber-500 bg-amber-100 text-amber-800' : 'border-border text-muted-foreground'}`}>+ Sem prazo {qtdSemPrazo}</button>}</div>{foraDoHorizonte > 0 && <p className="mt-2 text-xs text-amber-700">{foraDoHorizonte} pedido{foraDoHorizonte === 1 ? '' : 's'} deste card está fora do horizonte selecionado.</p>}</CardContent></Card>}
    {erro && <Card className="mb-4 border-destructive/50"><CardContent className="py-4 text-sm text-destructive">{erro}</CardContent></Card>}
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2"><Card><CardContent className="py-4"><div className="text-3xl font-semibold">{loading ? '—' : total}</div><div className="text-xs text-muted-foreground">pedidos neste lote</div></CardContent></Card><Card><CardContent className="py-4"><div className="text-3xl font-semibold">{loading ? '—' : Math.round(totalItens)}</div><div className="text-xs text-muted-foreground">itens na tabela</div></CardContent></Card></div>
    {!loading && total > 0 && <AcoesDoLote className="mb-4" params={chaveDoEscopo} titulo="Ações dos pedidos associados" mostrarIds={false} acoesExtras={<><Button type="button" variant="outline" size="sm" className="gap-2" onClick={copiar}><Copy className="h-4 w-4" /> Copiar</Button><PedidosAssociados pedidos={dados?.pedidos || []} /><Button type="button" size="sm" onClick={publicar} disabled={publicando || !previsaoVersao}>{publicando ? 'Publicando…' : `Publicar ${total}`}</Button></>} />}
    {!loading && total > 0 && <PreviaConsolidacao params={chaveDoEscopo} onLinhasChange={setLinhasEditadas} onBaseline={registrarBaseline} />}
    {conflitos.length > 0 && <Card className="mb-6 border-amber-400 bg-amber-50/60"><CardContent className="py-4 text-sm text-amber-900"><AlertTriangle className="mr-2 inline h-4 w-4" />{conflitos.length} pedido{conflitos.length > 1 ? 's' : ''} já estava{conflitos.length > 1 ? 'm' : ''} em outra consolidação aberta.</CardContent></Card>}
  </div>;
}
