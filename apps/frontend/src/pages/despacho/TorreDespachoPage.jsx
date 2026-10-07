import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { AlertTriangle, Clock, FileText, FileUp, Package, RefreshCw, Truck, Zap } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// A timeline agrupa por conta, lote logístico e dia limite de envio. A coleta
// apenas recomenda a próxima oportunidade; não altera a composição do lote.

const ABAS = [
  { id: 'hoje', rotulo: 'Hoje', ajuda: 'inclui atrasados e pedidos sem prazo e sem coleta disponível' },
  { id: 'amanha', rotulo: 'Amanhã', ajuda: 'prazo de postagem amanhã' },
  { id: 'proximos', rotulo: 'Próximos dias', ajuda: 'prazo mais adiante' },
];

// Espelha public.despacho_aba_do_bucket. Fica aqui como retaguarda: a API manda
// `aba` em cada bucket, mas a tela nao pode zerar so porque a API subiu depois
// do frontend — o operador leria isso como "nao ha pedido", que e a informacao
// mais errada que esta tela pode dar.
const ABA_DO_BUCKET = {
  atrasado: 'hoje', hoje: 'hoje', sem_prazo: 'hoje', amanha: 'amanha', depois: 'proximos',
};
const BUCKET_LABEL = {
  atrasado: 'Atrasado', hoje: 'Hoje', sem_prazo: 'Sem prazo', amanha: 'Amanhã', depois: 'Depois',
};
const BUCKET_ORDEM = ['atrasado', 'hoje', 'sem_prazo', 'amanha', 'depois'];
const abaDoBucket = (bucket) => bucket.aba || ABA_DO_BUCKET[bucket.bucket] || 'proximos';

function formatCompromisso(iso) {
  if (!iso) return null;
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return null;
  return data.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    timeZone: 'America/Sao_Paulo',
  });
}
const apenasHora = (iso) => formatCompromisso(iso)?.split(', ')[1] ?? null;

function ModalidadeCard({ marketplace, modalidade, aba, onAbrir }) {
  const qtd = modalidade.porAba[aba] ?? 0;
  const buckets = (modalidade.buckets || []).filter((b) => abaDoBucket(b) === aba);
  const temAtrasado = (buckets.find((b) => b.bucket === 'atrasado')?.qtd_pedidos || 0) > 0;
  const temSemPrazo = (buckets.find((b) => b.bucket === 'sem_prazo')?.qtd_pedidos || 0) > 0;
  const naoClassificada = modalidade.modalidade_id === null;
  const rascunho = modalidade.rascunho;

  // A coleta é o processo físico — o caminhão que vai passar — e é o prazo real
  // de produção. O corte NÃO é prazo: é a regra de pertencimento. Pedido pago
  // até o corte sai nessa coleta; pago depois, na próxima. Por isso o card diz
  // "lote fecha às", nunca "pronto até".
  const coleta = formatCompromisso(modalidade.coleta_em);
  const corte = apenasHora(modalidade.corte_em);
  const janelas = modalidade.janelas || [];
  const mercadoLivre = marketplace.module_id === 'mercadolivre';
  const coletasDoBucket = (() => {
    const agrupadas = new Map();
    for (const item of buckets.flatMap((bucket) => bucket.coletas || [])) {
      const chave = item.coleta_em || 'sem_coleta';
      const existente = agrupadas.get(chave);
      if (existente) existente.qtd_pedidos += item.qtd_pedidos || 0;
      else agrupadas.set(chave, { ...item });
    }
    return [...agrupadas.values()].sort((a, b) => (a.coleta_em || '9999').localeCompare(b.coleta_em || '9999'));
  })();
  const coletasComHorario = coletasDoBucket.filter((item) => item.coleta_em);
  const coletasLabel = coletasComHorario
    .slice(0, 4)
    .map((item) => `${formatCompromisso(item.coleta_em)} (${item.qtd_pedidos} ${item.qtd_pedidos === 1 ? 'pedido' : 'pedidos'})`)
    .join(' · ');

  const destaque = naoClassificada
    ? 'border-l-4 border-l-amber-500'
    : temAtrasado ? 'border-l-4 border-l-orange-500'
    : temSemPrazo ? 'border-l-4 border-l-amber-400' : '';
  const abrir = () => onAbrir({
    integrationId: marketplace.integration_id,
    modalidadeIds: modalidade.modalidade_ids || (modalidade.modalidade_id != null ? [modalidade.modalidade_id] : []),
    nomeMarketplace: marketplace.nome,
    nomeModalidade: modalidade.nome,
    naoClassificada,
  });

  return (
    <Card
      className={'cursor-pointer transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' + destaque}
      onClick={abrir}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          abrir();
        }
      }}
      role="button"
      tabIndex={0}
      aria-label={`Abrir ${modalidade.nome}, ${qtd} pedidos`}
    >
      <CardContent className="py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{modalidade.nome}</span>
              {modalidade.tipo_prazo === 'RELATIVO' && (
                <Badge variant="outline" className="text-[10px]">tempo real</Badge>
              )}
            </div>

            {!naoClassificada && !modalidade.coleta_em && (
              <div className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5" />
                sem janela cadastrada — usando o padrão do catálogo
              </div>
            )}
            {naoClassificada ? (
              <div className="mt-1 flex items-center gap-1 text-xs font-medium text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5" />
                canal sem regra cadastrada — clique para cadastrar
              </div>
            ) : mercadoLivre ? (
              <div className="mt-1 flex items-center gap-1 text-xs font-medium text-foreground">
                <Truck className="h-3.5 w-3.5" />
                {coletasLabel
                  ? `coleta atribuída: ${coletasLabel}${coletasComHorario.length > 4 ? ' · +' + (coletasComHorario.length - 4) + ' datas' : ''}`
                  : 'sem coleta configurada para este prazo'}
              </div>
            ) : coleta ? (
              <>
                <div className="mt-1 flex items-center gap-1 text-xs font-medium text-foreground">
                  <Truck className="h-3.5 w-3.5" />
                  próxima coleta {coleta}
                  {janelas.length > 1 && (
                    <span className="font-normal text-muted-foreground">
                      {' · envio até '}{apenasHora(modalidade.prazo_final_em)}
                      {janelas[janelas.length - 1]?.ponto_nome
                        ? ` (${janelas[janelas.length - 1].ponto_nome})` : ''}
                    </span>
                  )}
                </div>
                {corte && (
                  <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    lote fecha às {corte} — pago depois disso entra na próxima
                  </div>
                )}
              </>
            ) : null}
          </div>

          <div className="shrink-0 text-right">
            <div className="text-2xl font-semibold leading-none">{qtd}</div>
            <div className="text-[11px] text-muted-foreground">{qtd === 1 ? 'pedido' : 'pedidos'}</div>
          </div>
        </div>

        {buckets.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {buckets
              .slice()
              .sort((a, b) => BUCKET_ORDEM.indexOf(a.bucket) - BUCKET_ORDEM.indexOf(b.bucket))
              .map((bucket) => (
                <span
                  key={bucket.bucket}
                  className={
                    'rounded-full px-2 py-0.5 text-xs ' +
                    (bucket.bucket === 'atrasado' && bucket.qtd_pedidos > 0
                      ? 'bg-orange-100 text-orange-800'
                      : bucket.bucket === 'sem_prazo' && bucket.qtd_pedidos > 0
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-muted text-muted-foreground')
                  }
                >
                  {BUCKET_LABEL[bucket.bucket] || bucket.bucket}: {bucket.qtd_pedidos}
                </span>
              ))}
          </div>
        )}

        {rascunho && (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 text-white">
              <FileText className="h-3 w-3" />
              consolidação aberta: {rascunho.qtd_pedidos} pedidos
            </span>
            {rascunho.pedidos_ja_fora > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-orange-100 px-2 py-0.5 text-orange-800">
                <AlertTriangle className="h-3 w-3" />
                {rascunho.pedidos_ja_fora} saíram da pendência
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Nivel 3: tipo de envio.
function Banda({ titulo, ajuda, icone: Icone, tom, children }) {
  return (
    <div className="mb-6 last:mb-0">
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className={'flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide ' + (tom || 'text-muted-foreground')}>
          {Icone && <Icone className="h-3.5 w-3.5" />}
          {titulo}
        </h3>
        {ajuda && <span className="text-[11px] text-muted-foreground">{ajuda}</span>}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">{children}</div>
    </div>
  );
}

export default function TorreDespachoPage() {
  const [arvore, setArvore] = useState(null);
  const [marketplaceId, setMarketplaceId] = useState(null);
  const [aba, setAba] = useState('hoje');
  const [visualizacao, setVisualizacao] = useState('anterior');
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(null);
  const [atualizadoEm, setAtualizadoEm] = useState(null);
  const navigate = useNavigate();
  const requisicaoRef = useRef(null);
  const emCursoRef = useRef(false);


  const carregar = useCallback(async () => {
    requisicaoRef.current?.abort();
    const controller = new AbortController();
    requisicaoRef.current = controller;
    emCursoRef.current = true;
    setLoading(true);
    setErro(null);
    try {
      const hoje = dataOperacionalHoje();
      const res = await fetch(`/api/v2/despacho/arvore?data=${hoje}`, { signal: controller.signal });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar a torre de despacho');
      if (!controller.signal.aborted) {
        setArvore(json.data);
        setAtualizadoEm(new Date());
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setErro(err.message || 'Não foi possível carregar a torre. Tente atualizar.');
    } finally {
      if (!controller.signal.aborted) { emCursoRef.current = false; setLoading(false); }
    }
  }, []);

  useEffect(() => {
    carregar();
    // Pedido novo precisa aparecer sem o operador dar refresh.
    const id = setInterval(() => {
      if (!document.hidden && !emCursoRef.current) carregar();
    }, 60_000);
    return () => { clearInterval(id); requisicaoRef.current?.abort(); };
  }, [carregar]);

  useEffect(() => {
    if (!arvore || document.hidden) return undefined;
    const saidas = (arvore.lotes_timeline || [])
      .map((lote) => Date.parse(lote.proxima_saida_em || ''))
      .filter((instante) => Number.isFinite(instante) && instante > Date.now());
    if (saidas.length === 0) return undefined;
    const timer = window.setTimeout(() => {
      if (!emCursoRef.current) carregar();
    }, Math.max(1000, Math.min(...saidas) - Date.now() + 250));
    return () => window.clearTimeout(timer);
  }, [arvore, carregar]);

  // Reconstrói os totalizadores da visão anterior a partir dos mesmos buckets
  // entregues pela árvore; ela não depende da RPC nova da linha do tempo.
  const marketplaces = useMemo(() => {
    const saida = [];
    for (const mkt of arvore?.marketplaces || []) {
      const modalidades = [];
      const porAbaMkt = { hoje: 0, amanha: 0, proximos: 0 };
      for (const mod of mkt.modalidades || []) {
        const porAba = { hoje: 0, amanha: 0, proximos: 0 };
        for (const bucket of mod.buckets || []) {
          const destino = abaDoBucket(bucket);
          porAba[destino] += bucket.qtd_pedidos || 0;
          porAbaMkt[destino] += bucket.qtd_pedidos || 0;
        }
        modalidades.push({ ...mod, porAba });
      }
      const urgencia = (mod) => String(mod.coleta_em || mod.compromisso_mais_proximo || '9999');
      modalidades.sort((a, b) => urgencia(a).localeCompare(urgencia(b)));
      saida.push({
        integration_id: mkt.integration_id,
        module_id: mkt.module_id,
        nome: (mkt.nome || 'Origem não resolvida').trim(),
        total: mkt.qtd_pedidos ?? 0,
        composicao: mkt.composicao || [],
        porAba: porAbaMkt,
        maisUrgente: modalidades.length ? urgencia(modalidades[0]) : '9999',
        modalidades,
      });
    }
    saida.sort((a, b) => a.maisUrgente.localeCompare(b.maisUrgente));
    return saida;
  }, [arvore]);
  const lotes = useMemo(() => arvore?.lotes_timeline || [], [arvore]);
  const linhaTempoDisponivel = arvore?.linha_tempo_disponivel ?? Array.isArray(arvore?.lotes_timeline);
  const lotesVisiveis = useMemo(() => lotes.filter((lote) => {
    if (marketplaceId !== null && String(lote.integration_id) !== String(marketplaceId)) return false;
    return abaDoBucket({ bucket: lote.bucket }) === aba;
  }), [lotes, marketplaceId, aba]);
  const lotesDeAtencao = lotesVisiveis.filter((lote) =>
    !lote.data_limite_dia || lote.modalidade_id == null || !lote.proxima_saida_em
  );
  const lotesDaLinha = lotesVisiveis.filter((lote) => !lotesDeAtencao.includes(lote));
  const proximoLote = lotesDaLinha[0] || null;

  useEffect(() => {
    if (marketplaceId !== null && !marketplaces.some((m) => String(m.integration_id) === String(marketplaceId))) {
      setMarketplaceId(null);
    }
  }, [marketplaces, marketplaceId]);

  const abaJaEscolhida = useRef(false);
  useEffect(() => {
    if (abaJaEscolhida.current || marketplaces.length === 0) return;
    const primeiro = marketplaces[0];
    const comCarga = ABAS.find((item) => (primeiro.porAba[item.id] || 0) > 0);
    if (comCarga) setAba(comCarga.id);
    abaJaEscolhida.current = true;
  }, [marketplaces]);

  const atual = marketplaces.find((m) => String(m.integration_id) === String(marketplaceId)) || marketplaces[0] || null;
  const { semRegra, rapidas, comuns } = useMemo(() => {
    const linhas = (atual?.modalidades || []).filter((m) => (m.porAba[aba] || 0) > 0);
    return {
      semRegra: linhas.filter((m) => m.modalidade_id === null),
      rapidas: linhas.filter((m) => m.modalidade_id !== null && m.entrega_rapida),
      comuns: linhas.filter((m) => m.modalidade_id !== null && !m.entrega_rapida),
    };
  }, [atual, aba]);

  const abrirEscopo = ({ integrationId, modalidadeIds, nomeMarketplace, nomeModalidade, naoClassificada }) => {
    // Canal sem modalidade é fila de trabalho, não erro: o clique leva ao
    // cadastro da regra, não a uma lista que ninguém pode lançar com a janela
    // certa.
    if (naoClassificada) {
      navigate('/configuracoes/integracoes?aba=logistica&status=nao_classificado');
      return;
    }
    const params = new URLSearchParams();
    if (integrationId !== null && integrationId !== undefined) params.set('integration_id', integrationId);
    // O escopo e o lote inteiro: todos os canais que dividem a janela.
    // O singular vai junto de proposito: uma API que ainda nao conhece lotes le
    // `modalidade_id` e devolve o canal principal — menos do que o esperado, mas
    // nunca uma lista vazia. Ja aconteceu de a tela zerar por essa diferenca.
    (modalidadeIds || []).forEach((id) => params.append('modalidade_ids', id));
    if (modalidadeIds && modalidadeIds.length > 0) params.set('modalidade_id', modalidadeIds[0]);
    params.set('marketplace_nome', nomeMarketplace || '');
    params.set('modalidade_nome', nomeModalidade || '');
    params.set('aba', aba);
    navigate(`/despacho/escopo?${params.toString()}`);
  };

  const totaisPorAba = useMemo(() => lotes
    .filter((lote) => marketplaceId === null || String(lote.integration_id) === String(marketplaceId))
    .reduce((totais, lote) => {
    const destino = abaDoBucket({ bucket: lote.bucket });
    totais[destino] += lote.qtd_pedidos || 0;
    return totais;
  }, { hoje: 0, amanha: 0, proximos: 0 }), [lotes, marketplaceId]);
  const totaisAnteriores = useMemo(() => marketplaces
    .filter((marketplace) => marketplaceId === null || String(marketplace.integration_id) === String(marketplaceId))
    .reduce((totais, marketplace) => ({
      hoje: totais.hoje + (marketplace.porAba.hoje || 0),
      amanha: totais.amanha + (marketplace.porAba.amanha || 0),
      proximos: totais.proximos + (marketplace.porAba.proximos || 0),
    }), { hoje: 0, amanha: 0, proximos: 0 }), [marketplaces, marketplaceId]);
  const totaisTimeline = lotes.length ? totaisPorAba : totaisAnteriores;
  const semNada = !loading && marketplaces.length === 0 && lotes.length === 0;
  const abaVazia = atual && semRegra.length === 0 && rapidas.length === 0 && comuns.length === 0;
  const outrasAbasComCarga = atual
    ? ABAS.filter((item) => item.id !== aba && (atual.porAba[item.id] || 0) > 0)
    : [];
  const formatarSaida = (iso) => formatCompromisso(iso) || 'Horário não informado';
  const formatarDiaLimite = (lote) => {
    if (!lote.data_limite_dia) return 'Sem prazo de envio';
    if (lote.bucket === 'atrasado') return `Prazo vencido em ${new Date(`${lote.data_limite_dia}T12:00:00`).toLocaleDateString('pt-BR')}`;
    if (lote.data_limite_dia === arvore?.data) return 'Envio até hoje';
    const amanha = new Date(`${arvore?.data}T12:00:00`);
    amanha.setDate(amanha.getDate() + 1);
    if (lote.data_limite_dia === amanha.toLocaleDateString('sv-SE')) return 'Envio até amanhã';
    return `Envio até ${new Date(`${lote.data_limite_dia}T12:00:00`).toLocaleDateString('pt-BR')}`;
  };
  const paramsDoLote = (lote) => ({
    integrationId: lote.integration_id,
    modalidadeIds: lote.modalidade_ids,
    nomeMarketplace: lote.nome_marketplace,
    nomeModalidade: lote.nome_modalidade,
    naoClassificada: lote.modalidade_id == null,
  });

  return (
    <div className="p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Torre de despacho</h1>
          <p className="text-sm text-muted-foreground">
            {visualizacao === 'timeline'
              ? 'Veja a sequência dos lotes pela próxima coleta ou postagem.'
              : 'Confira os lotes por marketplace, prazo e tipo de envio.'}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div role="group" aria-label="Modo de visualização" className="inline-flex rounded-md border p-0.5">
            <Button
              type="button"
              size="sm"
              variant={visualizacao === 'anterior' ? 'default' : 'ghost'}
              aria-pressed={visualizacao === 'anterior'}
              onClick={() => setVisualizacao('anterior')}
            >
              Padrão
            </Button>
            <Button
              type="button"
              size="sm"
              variant={visualizacao === 'timeline' ? 'default' : 'ghost'}
              aria-pressed={visualizacao === 'timeline'}
              onClick={() => setVisualizacao('timeline')}
            >
              Linha do tempo
            </Button>
          </div>
          <button type="button" onClick={() => navigate('/despacho/arquivo')} className="flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
            <FileUp className="h-4 w-4" /> Conferir arquivo
          </button>
          <button type="button" onClick={carregar} className="flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
            <RefreshCw className={'h-4 w-4 ' + (loading ? 'animate-spin' : '')} /> Atualizar
          </button>
        </div>
      </div>

      {erro && (
        <Card className="mb-4 border-destructive/50">
          <CardContent className="py-4 text-sm text-destructive">
            {erro}{atualizadoEm && ` Os dados exibidos são da última atualização, às ${atualizadoEm.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}.`}
          </CardContent>
        </Card>
      )}

      {loading && !arvore && (
        <div className="space-y-3">
          <div className="h-12 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-28 w-full animate-pulse rounded-md bg-muted" />
        </div>
      )}

      {semNada && (
        <Card className="border-dashed">
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Nenhum pedido pendente de despacho no momento.
          </CardContent>
        </Card>
      )}

      {arvore && visualizacao === 'timeline' && (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1 border-b">
              {ABAS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setAba(item.id)}
                  aria-pressed={aba === item.id}
                  className={'-mb-px border-b-2 px-4 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' + (
                    aba === item.id
                      ? 'border-primary font-semibold text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground'
                  )}
                >
                  {item.rotulo}
                  <span className="ml-2 tabular-nums">{totaisTimeline[item.id] || 0}</span>
                </button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Marketplace</span>
              <select
                value={marketplaceId === null ? 'todos' : String(marketplaceId)}
                onChange={(event) => setMarketplaceId(event.target.value === 'todos' ? null : event.target.value)}
                className="h-10 min-w-48 rounded-md border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <option value="todos">Todos</option>
                {marketplaces.map((marketplace) => (
                  <option key={String(marketplace.integration_id)} value={String(marketplace.integration_id)}>
                    {marketplace.nome || 'Origem não resolvida'}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {atualizadoEm && !erro && (
            <p className="mb-4 text-right text-xs text-muted-foreground">
              Atualizado às {atualizadoEm.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
            </p>
          )}

          {proximoLote && (
            <Card className="mb-6 border-primary/50 bg-primary/[0.03]">
              <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
                <div>
                  <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
                    <Clock className="h-4 w-4" /> Próximo lote a conferir
                  </div>
                  <h2 className="text-lg font-semibold">
                    {proximoLote.nome_marketplace} · {proximoLote.nome_modalidade}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {formatarDiaLimite(proximoLote)} · Próxima coleta/postagem {formatarSaida(proximoLote.proxima_saida_em)}
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-2xl font-semibold tabular-nums">{proximoLote.qtd_pedidos}</div>
                    <div className="text-xs text-muted-foreground">pedidos</div>
                  </div>
                  <Button type="button" onClick={() => abrirEscopo(paramsDoLote(proximoLote))}>
                    {proximoLote.rascunho ? 'Continuar' : 'Conferir lote'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {lotesDeAtencao.length > 0 && (
            <section aria-labelledby="despacho-atencao" className="mb-7">
              <h2 id="despacho-atencao" className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-800">
                <AlertTriangle className="h-4 w-4" /> Precisa de atenção
              </h2>
              <div className="space-y-2">
                {lotesDeAtencao.map((lote) => (
                  <Card key={`${lote.integration_id}-${lote.lote_chave}-${lote.data_limite_dia || 'sem-prazo'}`}>
                    <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
                      <div>
                        <div className="font-medium">{lote.nome_marketplace} · {lote.nome_modalidade}</div>
                        <div className="text-sm text-muted-foreground">
                          {formatarDiaLimite(lote)} · {lote.modalidade_id == null
                            ? 'Canal sem regra logística'
                            : 'Nenhuma coleta/postagem disponível na agenda'}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="tabular-nums">{lote.qtd_pedidos} pedidos</span>
                        {lote.modalidade_id == null ? (
                          <Button type="button" variant="outline" onClick={() => abrirEscopo(paramsDoLote(lote))}>
                            Configurar canal
                          </Button>
                        ) : (
                          <Button type="button" variant="outline" onClick={() => abrirEscopo(paramsDoLote(lote))}>
                            Conferir lote
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="despacho-linha-do-tempo">
            <h2 id="despacho-linha-do-tempo" className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              <Truck className="h-4 w-4" /> Coletas e postagens — {ABAS.find((item) => item.id === aba)?.rotulo.toLowerCase()}
            </h2>
            {lotesDaLinha.length === 0 ? (
              <Card className="border-dashed">
                <CardContent className="py-8 text-center text-sm text-muted-foreground">
                  {!linhaTempoDisponivel
                    ? 'A linha do tempo ainda não está disponível. Use a visão anterior enquanto os dados são preparados.'
                    : lotes.length === 0 && marketplaces.some((marketplace) => marketplace.total > 0)
                      ? 'Há pedidos na visão anterior, mas a linha do tempo não retornou lotes. Atualize os dados ou volte à visão anterior.'
                      : 'Nenhum lote com coleta definida nesta visão.'}
                </CardContent>
              </Card>
            ) : (
              <ol className="relative ml-4 space-y-3 border-l-2 border-muted pl-6">
                {lotesDaLinha.map((lote, index) => {
                  const destaque = index === 0;
                  const minutos = Math.max(0, Math.ceil((Date.parse(lote.proxima_saida_em) - Date.now()) / 60_000));
                  const falta = minutos < 60 ? `Faltam ${minutos} min` : `Faltam ${Math.floor(minutos / 60)} h ${minutos % 60} min`;
                  return (
                    <li key={`${lote.integration_id}-${lote.lote_chave}-${lote.data_limite_dia}`} className="relative">
                      <span className={'absolute -left-[33px] top-5 h-4 w-4 rounded-full border-2 border-background ' + (
                        destaque ? 'bg-primary ring-2 ring-primary/20' : 'bg-muted-foreground'
                      )} aria-hidden="true" />
                      <Card className={destaque ? 'border-primary/40' : ''}>
                        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
                          <div className="min-w-0">
                            <div className="mb-1 flex flex-wrap items-center gap-2">
                              <span className="text-base font-semibold">{formatarSaida(lote.proxima_saida_em)}</span>
                              {destaque && <Badge>Próximo lote</Badge>}
                              {lote.entrega_rapida && <Badge variant="outline">Entrega rápida</Badge>}
                              {lote.bucket === 'atrasado' && <Badge variant="destructive">Prazo vencido</Badge>}
                            </div>
                            <div className="font-medium">{lote.nome_marketplace} · {lote.nome_modalidade}</div>
                            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                              <span>{formatarDiaLimite(lote)}</span>
                              {lote.saida_apos_prazo && (
                                <span className="font-medium text-amber-700">Coleta após o prazo de envio</span>
                              )}
                              {destaque && <span>{falta}</span>}
                              {lote.rascunho?.qtd_pedidos > 0 && (
                                <span className="inline-flex items-center gap-1">
                                  <FileText className="h-3.5 w-3.5" />
                                  consolidação aberta: {lote.rascunho.qtd_pedidos} pedidos
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <div className="text-right">
                              <div className="text-2xl font-semibold tabular-nums">{lote.qtd_pedidos}</div>
                              <div className="text-xs text-muted-foreground">{lote.qtd_pedidos === 1 ? 'pedido' : 'pedidos'}</div>
                            </div>
                            <Button type="button" variant={destaque ? 'default' : 'outline'} onClick={() => abrirEscopo(paramsDoLote(lote))}>
                              {lote.rascunho ? 'Continuar' : 'Conferir lote'}
                            </Button>
                          </div>
                        </CardContent>
                      </Card>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </>
      )}

      {arvore && visualizacao === 'anterior' && (
        <>
          {atualizadoEm && !erro && (
            <p className="mb-4 text-right text-xs text-muted-foreground">
              Atualizado às {atualizadoEm.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
            </p>
          )}

          {atual ? (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {marketplaces.map((marketplace) => {
                  const ativo = String(marketplace.integration_id) === String(atual.integration_id);
                  return (
                    <button
                      key={String(marketplace.integration_id)}
                      type="button"
                      onClick={() => setMarketplaceId(marketplace.integration_id)}
                      className={'flex items-center gap-2 rounded-lg border px-4 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' + (
                        ativo
                          ? 'border-primary bg-primary/5 font-semibold text-foreground'
                          : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'
                      )}
                    >
                      <Package className={'h-4 w-4 ' + (ativo ? '' : 'opacity-60')} />
                      {marketplace.nome}
                      <span className="tabular-nums">{marketplace.total}</span>
                    </button>
                  );
                })}
              </div>

              <div className="mb-6 flex flex-wrap gap-1 border-b">
                {ABAS.map((item) => {
                  const ativa = item.id === aba;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setAba(item.id)}
                      title={item.ajuda}
                      aria-pressed={ativa}
                      className={'-mb-px border-b-2 px-4 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' + (
                        ativa
                          ? 'border-primary font-semibold text-foreground'
                          : 'border-transparent text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {item.rotulo}
                      <span className={'ml-2 tabular-nums ' + (ativa ? 'font-semibold' : '')}>
                        {atual.porAba[item.id] || 0}
                      </span>
                    </button>
                  );
                })}
              </div>

              {atual.composicao.length > 1 && (
                <div className="-mt-3 mb-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground tabular-nums">{atual.total}</span>
                  <span>pendentes de despacho =</span>
                  {atual.composicao.map((item, index) => (
                    <span key={item.situacao_id}>
                      {index > 0 && <span className="mr-2">+</span>}
                      <span className="tabular-nums text-foreground">{item.qtd_pedidos}</span>{' '}
                      {item.situacao.toLowerCase()}
                    </span>
                  ))}
                </div>
              )}

              {abaVazia && (
                <Card className="border-dashed">
                  <CardContent className="py-8 text-center text-sm">
                    <p className="text-muted-foreground">
                      {atual.nome} não tem pedidos{' '}
                      {aba === 'hoje' ? 'para hoje' : aba === 'amanha' ? 'para amanhã' : 'nos próximos dias'}.
                    </p>
                    {outrasAbasComCarga.length > 0 && (
                      <div className="mt-3 flex flex-wrap justify-center gap-2">
                        {outrasAbasComCarga.map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setAba(item.id)}
                            className="rounded-full border border-primary/40 px-3 py-1 text-xs text-primary transition-colors hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                          >
                            {item.rotulo}: {atual.porAba[item.id]} pedidos
                          </button>
                        ))}
                      </div>
                    )}
                    {atual.total === 0 && (
                      <p className="mt-2 text-xs text-muted-foreground">Nada pendente neste marketplace.</p>
                    )}
                  </CardContent>
                </Card>
              )}

              {semRegra.length > 0 && (
                <Banda
                  titulo="Sem regra logística"
                  ajuda="prioridade máxima — clique para cadastrar o canal"
                  icone={AlertTriangle}
                  tom="text-amber-700"
                >
                  {semRegra.map((modalidade) => (
                    <ModalidadeCard key="sem-regra" marketplace={atual} modalidade={modalidade} aba={aba} onAbrir={abrirEscopo} />
                  ))}
                </Banda>
              )}

              {rapidas.length > 0 && (
                <Banda titulo="Entrega rápida" ajuda="não espera o corte do lote comum" icone={Zap} tom="text-amber-700">
                  {rapidas.map((modalidade) => (
                    <ModalidadeCard key={modalidade.lote_chave} marketplace={atual} modalidade={modalidade} aba={aba} onAbrir={abrirEscopo} />
                  ))}
                </Banda>
              )}

              {comuns.length > 0 && (
                <Banda
                  titulo="Lote comum"
                  ajuda={atual.module_id === 'mercadolivre'
                    ? 'coletas agrupadas pela data limite de envio'
                    : 'ordenado pela próxima coleta'}
                  icone={Truck}
                >
                  {comuns.map((modalidade) => (
                    <ModalidadeCard key={modalidade.lote_chave} marketplace={atual} modalidade={modalidade} aba={aba} onAbrir={abrirEscopo} />
                  ))}
                </Banda>
              )}
            </>
          ) : (
            <Card className="border-dashed">
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                Nenhum marketplace com pedidos pendentes nesta visão.
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
