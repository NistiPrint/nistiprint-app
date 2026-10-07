import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import PacoteBadge from '@/components/pedidos/PacoteBadge';
import AcoesDoLote from '@/components/despacho/AcoesDoLote';
import ConferenciaDoArquivo from '@/components/despacho/ConferenciaDoArquivo';
import LinhasConsolidadas from '@/components/despacho/LinhasConsolidadas';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { horizonteDaAba, alternarPrazo } from '@/lib/escopoDespacho';
import { linhasForamEditadas, prepararLinhasParaEnvio, totalizarLinhas, linhasParaTsv } from '@/lib/consolidacaoEditavel';
import { carregarEscopoDespacho } from '@/lib/despachoEscopo';
import { AlertTriangle, ArrowLeft, ChevronRight, Copy, ExternalLink, MoreHorizontal, Printer } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import capaPrintService from '@/services/capaPrintService';

const HORIZONTE_STEPS = ['atrasado', 'hoje', 'amanha', 'depois'];
const HORIZONTE_LABEL = { atrasado: 'Atrasado', hoje: 'Hoje', amanha: 'Amanhã', depois: 'Depois' };
const IDS_POR_BLOCO = 100;

function parseIntOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const numero = parseInt(value, 10);
  return Number.isNaN(numero) ? null : numero;
}

function PedidosAssociados({ pedidos = [] }) {
  const ids = pedidos.map((pedido) => pedido.marketplace_order_id || pedido.codigo_pedido_externo).filter(Boolean);
  const blocosIds = [];
  for (let inicio = 0; inicio < ids.length; inicio += IDS_POR_BLOCO) {
    const idsDoBloco = ids.slice(inicio, inicio + IDS_POR_BLOCO);
    blocosIds.push({
      inicio: inicio + 1,
      fim: inicio + idsDoBloco.length,
      texto: idsDoBloco.join(';'),
    });
  }
  const copiarIds = async (bloco) => {
    try {
      await navigator.clipboard.writeText(bloco.texto);
      toast.success(`IDs ${bloco.inicio} a ${bloco.fim} copiados.`);
    } catch {
      toast.error('Não foi possível copiar os IDs.');
    }
  };
  return (
    <Sheet>
      <SheetTrigger asChild><Button type="button" variant="outline" size="icon" aria-label="Mais ações"><MoreHorizontal className="h-4 w-4" /></Button></SheetTrigger>
      <SheetContent side="right" className="w-[96vw] overflow-y-auto sm:max-w-3xl">
        <SheetHeader><SheetTitle>Pedidos associados ({pedidos.length})</SheetTitle></SheetHeader>
        {blocosIds.length > 0 && <div className="mt-5 space-y-2 rounded-md border bg-muted/30 p-3"><div className="text-xs font-medium">IDs do Bling/marketplace, em blocos de até {IDS_POR_BLOCO}</div>{blocosIds.map((bloco) => <div key={bloco.inicio} className="flex items-center gap-2"><div className="min-w-0 flex-1"><div className="mb-1 text-xs text-muted-foreground">IDs {bloco.inicio} a {bloco.fim}</div><div className="truncate font-mono text-xs text-muted-foreground" title={bloco.texto}>{bloco.texto}</div></div><Button type="button" variant="outline" size="sm" className="shrink-0 gap-2" onClick={() => copiarIds(bloco)}><Copy className="h-4 w-4" /> Copiar</Button></div>)}</div>}
        {pedidos.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">Nenhum pedido associado.</p> : <div className="mt-4 overflow-x-auto rounded-md border"><table className="w-full min-w-[680px] text-sm"><thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Pedido</th><th className="px-3 py-2">ID no marketplace</th><th className="px-3 py-2">Cliente</th><th className="px-3 py-2">Total</th><th className="px-3 py-2">Prazo</th><th className="px-3 py-2">Envio</th></tr></thead><tbody>{pedidos.map((pedido) => <tr key={pedido.id} className="border-t"><td className="px-3 py-2"><div className="flex items-center gap-2"><span>{pedido.numero_pedido || pedido.codigo_pedido_externo}</span><PacoteBadge variant="inline" irmaos={pedido.pack_irmaos} irmaosIds={pedido.pack_irmaos_ids} /></div></td><td className="px-3 py-2 font-mono text-xs">{pedido.marketplace_order_id || pedido.codigo_pedido_externo || '—'}</td><td className="px-3 py-2">{pedido.cliente_nome || '—'}</td><td className="px-3 py-2">{pedido.total_pedido == null ? '—' : Number(pedido.total_pedido).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</td><td className="px-3 py-2">{pedido.data_limite_envio ? new Date(pedido.data_limite_envio).toLocaleDateString('pt-BR') : pedido.data_coleta_prevista ? `Coleta ${new Date(pedido.data_coleta_prevista).toLocaleDateString('pt-BR')}` : 'não informado'}</td><td className="px-3 py-2">{pedido.metodo_envio_rotulo || 'não classificado'}</td></tr>)}</tbody></table></div>}
      </SheetContent>
    </Sheet>
  );
}

export default function EscopoDespachoPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const integrationId = parseIntOrNull(searchParams.get('integration_id'));
  const conferenciaId = parseIntOrNull(searchParams.get('conferencia_id'));
  const origemArquivo = conferenciaId !== null;
  const modalidadeIds = useMemo(() => { const lista = searchParams.getAll('modalidade_ids').map(parseIntOrNull).filter((valor) => valor !== null); if (lista.length) return lista; const unico = parseIntOrNull(searchParams.get('modalidade_id')); return unico === null ? [] : [unico]; }, [searchParams]);
  const marketplaceNome = searchParams.get('marketplace_nome') || 'Origem não resolvida';
  const modalidadeNome = searchParams.get('modalidade_nome') || 'Modalidade não classificada';
  const abaOrigem = searchParams.get('aba') || 'hoje';
  const identidadeOrigem = `${integrationId ?? ''}/${modalidadeIds.join(',')}/${conferenciaId ?? ''}/${abaOrigem}`;
  const [horizonte, setHorizonte] = useState(() => horizonteDaAba(abaOrigem));
  const [dataReferencia, setDataReferencia] = useState(() => dataOperacionalHoje());
  const [dados, setDados] = useState(null);
  const [loading, setLoading] = useState(true);
  const [publicando, setPublicando] = useState(false);
  const [conflitos, setConflitos] = useState([]);
  const [erro, setErro] = useState(null);
  const [linhasEditadas, setLinhasEditadas] = useState([]);
  const [previsaoVersao, setPrevisaoVersao] = useState(null);
  const [planoImpressao, setPlanoImpressao] = useState(null);
  const [abrindoPlano, setAbrindoPlano] = useState(false);
  const baselineRef = useRef([]);
  const requisicaoRef = useRef(null);
  const identidadeOrigemRef = useRef(identidadeOrigem);
  const incluirSemPrazo = horizonte.includes('sem_prazo');
  const chaveDoEscopo = useMemo(() => origemArquivo ? { conferencia_id: conferenciaId } : { integration_id: integrationId ?? undefined, modalidade_ids: modalidadeIds, modalidade_id: modalidadeIds[0] ?? undefined, horizonte, data: dataReferencia }, [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte, dataReferencia]);
  const carregar = useCallback(async () => {
    requisicaoRef.current?.abort();
    const controller = new AbortController();
    requisicaoRef.current = controller;
    setLoading(true); setErro(null); setDados(null); setLinhasEditadas([]); baselineRef.current = []; setPrevisaoVersao(null); setPlanoImpressao(null);
    try {
      const params = new URLSearchParams();
      if (origemArquivo) params.set('conferencia_id', conferenciaId);
      else {
        if (integrationId !== null) params.set('integration_id', integrationId);
        modalidadeIds.forEach((id) => params.append('modalidade_ids', id));
        if (modalidadeIds.length) params.set('modalidade_id', modalidadeIds[0]);
        horizonte.forEach((item) => params.append('horizonte', item));
        params.set('data', dataReferencia);
      }
      params.set('incluir_previsao', '1');
      const escopo = await carregarEscopoDespacho(fetch, params, controller.signal);
      if (controller.signal.aborted) return;
      baselineRef.current = escopo.previsao.itens;
      setLinhasEditadas(baselineRef.current);
      setPrevisaoVersao(escopo.previsao.previsao_versao);
      setDados(escopo);
    } catch (err) {
      if (!controller.signal.aborted) setErro(err.message || 'Não foi possível carregar o escopo.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte, dataReferencia]);
  useEffect(() => { carregar(); return () => requisicaoRef.current?.abort(); }, [carregar]);
  useEffect(() => {
    const verificarDiaOperacional = () => {
      const hoje = dataOperacionalHoje();
      setDataReferencia((anterior) => anterior === hoje ? anterior : hoje);
    };
    const timer = window.setInterval(verificarDiaOperacional, 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const publicar = async () => {
    setPublicando(true); setConflitos([]);
    try {
      const planoAtual = planoImpressao?.id
        ? await capaPrintService.savePlan({ pedido_ids: (dados?.pedidos || []).map((pedido) => pedido.id).filter(Boolean), linhas: prepararLinhasParaEnvio(linhasEditadas), previsao_versao: previsaoVersao })
        : null;
      const lancamento = await fetch('/api/v2/despacho/lancar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ integration_id: integrationId, modalidade_ids: modalidadeIds, modalidade_id: modalidadeIds[0] ?? null, horizonte, data: dataReferencia, ...(origemArquivo ? { conferencia_id: conferenciaId } : {}), previsao_versao: previsaoVersao }) });
      const criado = await lancamento.json(); if (!criado.success) throw new Error(criado.error || 'Não foi possível montar a demanda');
      setConflitos(criado.data.ja_em_rascunho || []);
      const linhas = temAlteracoes ? prepararLinhasParaEnvio(linhasEditadas) : undefined;
      const publicado = await fetch('/api/v2/despacho/publicar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ demanda_id: criado.data.demanda_id, ...(planoAtual?.id ? { plano_impressao_id: planoAtual.id } : {}), ...(linhas ? { linhas, previsao_versao: previsaoVersao } : {}) }) });
      const json = await publicado.json(); if (!json.success) throw new Error(json.error || 'Não foi possível publicar');
      toast.success(`${json.data.demanda_codigo} publicada — ${json.data.total_pedidos} pedidos foram para produção`); navigate('/despacho');
    } catch (err) { toast.error(err.message || 'Não foi possível publicar a demanda'); } finally { setPublicando(false); }
  };
  const copiar = async () => {
    try { await navigator.clipboard.writeText(linhasParaTsv(linhasEditadas)); toast.success('Tabela copiada para a planilha.'); }
    catch { toast.error('Não foi possível copiar a tabela.'); }
  };
  const total = dados?.total ?? 0;
  const totalItens = useMemo(() => totalizarLinhas(linhasEditadas), [linhasEditadas]);
  const totalNo = dados?.total_no ?? total;
  const foraDoHorizonte = Math.max(0, totalNo - total);
  const qtdSemPrazo = dados?.buckets?.sem_prazo ?? 0;
  const temAlteracoes = useMemo(() => linhasForamEditadas(linhasEditadas, baselineRef.current), [linhasEditadas]);
  const confirmarDescarte = useCallback(() => !temAlteracoes || window.confirm('Existem alterações não publicadas. Deseja descartá-las?'), [temAlteracoes]);
  useEffect(() => {
    if (identidadeOrigemRef.current === identidadeOrigem) return;
    if (!confirmarDescarte()) {
      navigate('/despacho');
      return;
    }
    identidadeOrigemRef.current = identidadeOrigem;
    setHorizonte(horizonteDaAba(abaOrigem));
  }, [identidadeOrigem, abaOrigem, confirmarDescarte, navigate]);
  const pedidoIds = useMemo(() => (dados?.pedidos || []).map((pedido) => pedido.id).filter(Boolean), [dados?.pedidos]);
  const linhasParaImpressao = useMemo(() => prepararLinhasParaEnvio(linhasEditadas), [linhasEditadas]);
  const abrirPlano = async () => {
    // A guia é criada no clique para que o bloqueador de pop-ups não interrompa a navegação.
    const guia = window.open('', '_blank');
    if (!guia) { toast.error('Permita a abertura de novas guias para ver o plano.'); return; }
    guia.document.title = 'Preparando plano de impressão';
    guia.document.body.textContent = 'Preparando plano de impressão…';
    setAbrindoPlano(true);
    try {
      const plano = await capaPrintService.savePlan({ pedido_ids: pedidoIds, linhas: linhasParaImpressao, previsao_versao: previsaoVersao });
      setPlanoImpressao(plano);
      guia.location.replace(`/despacho/plano-impressao?plano_id=${encodeURIComponent(plano.id)}`);
    } catch (error) {
      guia.close();
      toast.error('Plano de impressão: ' + error.message);
    } finally { setAbrindoPlano(false); }
  };
  return <div className="p-6">
    <button type="button" onClick={() => confirmarDescarte() && navigate('/despacho')} className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Voltar para a torre de despacho</button>
    <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">{origemArquivo && <><span>📄 conferência de arquivo</span><ChevronRight className="h-3.5 w-3.5" /></>}<span>{marketplaceNome}</span><ChevronRight className="h-3.5 w-3.5" /><span className="font-medium text-foreground">{modalidadeNome}</span></div>
    {origemArquivo && <ConferenciaDoArquivo conferenciaId={conferenciaId} onMudou={carregar} />}
    {!origemArquivo && <Card className="mb-6"><CardContent className="py-5"><div className="mb-3 text-sm font-medium">Datas de envio</div><div className="flex flex-wrap gap-2">{HORIZONTE_STEPS.map((step) => <button key={step} type="button" onClick={() => confirmarDescarte() && setHorizonte((atual) => alternarPrazo(atual, step))} className={`rounded-full border px-3 py-1 text-xs ${horizonte.includes(step) ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>{HORIZONTE_LABEL[step]} {dados?.buckets?.[step] ? <span className="ml-1.5 opacity-70">{dados.buckets[step]}</span> : null}</button>)}{qtdSemPrazo > 0 && <button type="button" onClick={() => confirmarDescarte() && setHorizonte((atual) => alternarPrazo(atual, 'sem_prazo'))} className={`rounded-full border px-3 py-1 text-xs ${incluirSemPrazo ? 'border-amber-500 bg-amber-100 text-amber-800' : 'border-border text-muted-foreground'}`}>+ Sem prazo {qtdSemPrazo}</button>}</div>{foraDoHorizonte > 0 && <p className="mt-2 text-xs text-amber-700">{foraDoHorizonte} pedido{foraDoHorizonte === 1 ? '' : 's'} deste card está fora do horizonte selecionado.</p>}</CardContent></Card>}
    {erro && <Card className="mb-4 border-destructive/50"><CardContent className="py-4 text-sm text-destructive">{erro}</CardContent></Card>}
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2"><Card><CardContent className="py-4"><div className="text-3xl font-semibold">{loading ? '—' : total}</div><div className="text-xs text-muted-foreground">pedidos neste lote</div></CardContent></Card><Card><CardContent className="py-4"><div className="text-3xl font-semibold">{loading ? '—' : Math.round(totalItens)}</div><div className="text-xs text-muted-foreground">itens na tabela</div></CardContent></Card></div>
    {!erro && total > 0 && <AcoesDoLote className="mb-4" dadosIniciais={dados?.acoes} onAtualizar={() => confirmarDescarte() && carregar()} params={chaveDoEscopo} titulo="Ações dos pedidos associados" mostrarIds={false} acoesExtras={<><Button type="button" variant="outline" size="sm" className="gap-2" onClick={copiar}><Copy className="h-4 w-4" /> Copiar</Button><PedidosAssociados pedidos={dados?.pedidos || []} /><Button type="button" variant="outline" size="sm" className="gap-2" onClick={abrirPlano} disabled={abrindoPlano || !previsaoVersao} title="Abre o plano em uma nova guia"><Printer className="h-4 w-4" /> {abrindoPlano ? 'Preparando…' : 'Plano de impressão'} <ExternalLink className="h-3.5 w-3.5" /></Button><Button type="button" size="sm" onClick={publicar} disabled={publicando || !previsaoVersao}>{publicando ? 'Publicando…' : `Publicar ${total}`}</Button></>} />}
    {!loading && !erro && total > 0 && <LinhasConsolidadas key={`${JSON.stringify(chaveDoEscopo)}-${previsaoVersao}`} itens={dados?.previsao?.itens || []} resumo={dados?.previsao} onChange={setLinhasEditadas} />}
    {conflitos.length > 0 && <Card className="mb-6 border-amber-400 bg-amber-50/60"><CardContent className="py-4 text-sm text-amber-900"><AlertTriangle className="mr-2 inline h-4 w-4" />{conflitos.length} pedido{conflitos.length > 1 ? 's' : ''} já estava{conflitos.length > 1 ? 'm' : ''} em outra consolidação aberta.</CardContent></Card>}
  </div>;
}
