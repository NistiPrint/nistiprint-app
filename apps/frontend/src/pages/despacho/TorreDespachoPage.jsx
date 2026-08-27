import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { AlertTriangle, Clock, FileText, Package, RefreshCw, Truck, Zap } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// Torre de despacho — N0 da navegacao por contexto.
// Contrato: docs/specs/02-domains/despacho/spec.md
//
// A navegacao tem tres niveis, nesta ordem:
//
//   1. Marketplace     — qual painel o operador esta conferindo
//   2. Data de envio   — o que sai hoje, amanha, depois
//   3. Tipo de envio   — o que nao pode esperar o corte do lote comum
//
// Cada card e um LOTE, nao uma modalidade: canais que compartilham a janela
// saem no mesmo caminhao e por isso viram um card so ("Comum + Retirada pelo
// Comprador"). Dois cards para a mesma coleta virariam dois lotes de producao
// para um caminhao.
//
// O marketplace vem primeiro porque o numero existe para ser conferido, e a
// conferencia e sempre contra UM painel por vez. Um contador que soma Shopee
// com Mercado Livre nao corresponde a nenhuma tela que o operador consegue
// abrir do outro lado.
//
// Nunca exibe lista de pedidos: clicar num card leva ao escopo (N1).
//
// Duas invariantes que a interface nao pode quebrar:
//  - Nenhuma contagem e propria. Tudo e derivado dos buckets que a arvore ja
//    devolve, entao nao existe um segundo numero para a mesma pergunta.
//  - Consolidacao aberta e marcador, nunca subtracao: o total do card continua
//    sendo todos os pedidos pendentes daquele no. (No banco o status ainda se
//    chama RASCUNHO; na tela, nunca — "rascunho" sugere esboco descartavel,
//    quando e o lote fechado sobre o qual o operador ja emitiu nota.)

const ABAS = [
  { id: 'hoje', rotulo: 'Hoje', ajuda: 'inclui atrasados e pedidos sem prazo informado' },
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
const abaDoBucket = (bucket) => bucket.aba || ABA_DO_BUCKET[bucket.bucket] || 'proximos';

const BUCKET_LABEL = {
  atrasado: 'Atrasado', hoje: 'Hoje', amanha: 'Amanhã', depois: 'Depois', sem_prazo: 'Sem prazo',
};
const BUCKET_ORDEM = ['atrasado', 'hoje', 'sem_prazo', 'amanha', 'depois'];

function formatCompromisso(iso) {
  if (!iso) return null;
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return null;
  return data.toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
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

  const destaque = naoClassificada
    ? 'border-l-4 border-l-amber-500'
    : temAtrasado ? 'border-l-4 border-l-orange-500'
    : temSemPrazo ? 'border-l-4 border-l-amber-400' : '';

  return (
    <Card
      className={'cursor-pointer transition-colors hover:border-primary/60 ' + destaque}
      onClick={() => onAbrir({
        integrationId: marketplace.integration_id,
        modalidadeIds: modalidade.modalidade_ids || (modalidade.modalidade_id != null ? [modalidade.modalidade_id] : []),
        nomeMarketplace: marketplace.nome,
        nomeModalidade: modalidade.nome,
        naoClassificada,
      })}
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
            {modalidade.qtd_pedidos !== qtd && (
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                {modalidade.qtd_pedidos} no total
              </div>
            )}
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
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(null);
  const navigate = useNavigate();

  useSecaoSidebar();

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const hoje = dataOperacionalHoje();
      const res = await fetch(`/api/v2/despacho/arvore?data=${hoje}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar a torre de despacho');
      setArvore(json.data);
    } catch (err) {
      setErro(err.message || 'Não foi possível carregar a torre. Tente atualizar.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    carregar();
    // Pedido novo precisa aparecer sem o operador dar refresh.
    const id = setInterval(carregar, 60_000);
    return () => clearInterval(id);
  }, [carregar]);

  // Tudo abaixo é derivado dos buckets da árvore. Nenhuma contagem própria.
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

  // Mantém a seleção entre refreshes; cai no primeiro quando o nó escolhido
  // deixa de existir (todos os pedidos dele foram publicados, por exemplo).
  useEffect(() => {
    if (marketplaces.length === 0) return;
    if (!marketplaces.some((m) => m.integration_id === marketplaceId)) {
      setMarketplaceId(marketplaces[0].integration_id);
    }
  }, [marketplaces, marketplaceId]);

  // Abre numa aba que tenha pedido. Hoje costuma ser a pergunta do operador,
  // mas nem sempre tem carga: em 26/08 o Mercado Livre tinha 0 hoje e 13
  // amanhã. Abrir numa aba legitimamente vazia faz a torre parecer quebrada, e
  // "não há pedido" é a informação mais errada que esta tela pode dar.
  // Só vale para a primeira carga: depois disso a escolha é do operador.
  const abaJaEscolhida = useRef(false);
  useEffect(() => {
    if (abaJaEscolhida.current || marketplaces.length === 0) return;
    const primeiro = marketplaces[0];
    const comCarga = ABAS.find((a) => (primeiro.porAba[a.id] ?? 0) > 0);
    if (comCarga) setAba(comCarga.id);
    abaJaEscolhida.current = true;
  }, [marketplaces]);

  const atual = marketplaces.find((m) => m.integration_id === marketplaceId) || marketplaces[0] || null;

  const { semRegra, rapidas, comuns } = useMemo(() => {
    const linhas = (atual?.modalidades || []).filter((m) => (m.porAba[aba] ?? 0) > 0);
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

  const semNada = !loading && marketplaces.length === 0;
  const abaVazia = atual && semRegra.length === 0 && rapidas.length === 0 && comuns.length === 0;
  const outrasAbasComCarga = atual
    ? ABAS.filter((a) => a.id !== aba && (atual.porAba[a.id] ?? 0) > 0)
    : [];

  return (
    <div className="p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Torre de despacho</h1>
          <p className="text-sm text-muted-foreground">
            Escolha o marketplace, confira o total contra o painel dele e consolide o lote.
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

      {atual && (
        <>
          {/* Nível 1 — marketplace */}
          <div className="mb-4 flex flex-wrap gap-2">
            {marketplaces.map((m) => {
              const ativo = m.integration_id === atual.integration_id;
              return (
                <button
                  key={String(m.integration_id)}
                  type="button"
                  onClick={() => setMarketplaceId(m.integration_id)}
                  className={
                    'flex items-center gap-2 rounded-lg border px-4 py-2 text-sm transition-colors ' +
                    (ativo
                      ? 'border-primary bg-primary/5 font-semibold text-foreground'
                      : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground')
                  }
                >
                  <Package className={'h-4 w-4 ' + (ativo ? '' : 'opacity-60')} />
                  {m.nome}
                  <span className="tabular-nums">{m.total}</span>
                </button>
              );
            })}
          </div>

          {/* Nível 2 — data de envio, já filtrada pelo marketplace escolhido */}
          <div className="mb-6 flex flex-wrap gap-1 border-b">
            {ABAS.map((a) => {
              const ativa = a.id === aba;
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => setAba(a.id)}
                  title={a.ajuda}
                  className={
                    '-mb-px border-b-2 px-4 py-2 text-sm transition-colors ' +
                    (ativa
                      ? 'border-primary font-semibold text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground')
                  }
                >
                  {a.rotulo}
                  <span className={'ml-2 tabular-nums ' + (ativa ? 'font-semibold' : '')}>
                    {atual.porAba[a.id] ?? 0}
                  </span>
                </button>
              );
            })}
          </div>

          {/* De onde vem o total. A tela de Pedidos filtrada por "Em Andamento"
              mostra menos, porque a torre também conta o que já foi produzido e
              ainda não saiu — continua sendo trabalho do galpão. Sem esta linha
              a diferença parece erro, e o operador confere duas telas para
              descobrir que nenhuma das duas está errada. */}
          {atual.composicao.length > 1 && (
            <div className="-mt-3 mb-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className="font-medium text-foreground tabular-nums">{atual.total}</span>
              <span>pendentes de despacho =</span>
              {atual.composicao.map((c, i) => (
                <span key={c.situacao_id}>
                  {i > 0 && <span className="mr-2">+</span>}
                  <span className="tabular-nums text-foreground">{c.qtd_pedidos}</span>{' '}
                  {c.situacao.toLowerCase()}
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
                {/* Vazio nunca é beco sem saída: se há carga em outra aba, ela
                    aparece aqui como caminho. */}
                {outrasAbasComCarga.length > 0 && (
                  <div className="mt-3 flex flex-wrap justify-center gap-2">
                    {outrasAbasComCarga.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => setAba(a.id)}
                        className="rounded-full border border-primary/40 px-3 py-1 text-xs text-primary transition-colors hover:bg-primary/5"
                      >
                        {a.rotulo}: {atual.porAba[a.id]} pedidos
                      </button>
                    ))}
                  </div>
                )}
                {atual.total === 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Nada pendente neste marketplace.
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Nível 3 — tipo de envio. Sem regra vem primeiro e nunca colapsa:
              prazo desconhecido é tratado como a hipótese mais urgente. */}
          {semRegra.length > 0 && (
            <Banda
              titulo="Sem regra logística"
              ajuda="prioridade máxima — clique para cadastrar o canal"
              icone={AlertTriangle}
              tom="text-amber-700"
            >
              {semRegra.map((mod) => (
                <ModalidadeCard key="sem-regra" marketplace={atual} modalidade={mod} aba={aba} onAbrir={abrirEscopo} />
              ))}
            </Banda>
          )}

          {rapidas.length > 0 && (
            <Banda titulo="Entrega rápida" ajuda="não espera o corte do lote comum" icone={Zap} tom="text-amber-700">
              {rapidas.map((mod) => (
                <ModalidadeCard key={mod.lote_chave} marketplace={atual} modalidade={mod} aba={aba} onAbrir={abrirEscopo} />
              ))}
            </Banda>
          )}

          {comuns.length > 0 && (
            <Banda titulo="Lote comum" ajuda="ordenado pela próxima coleta" icone={Truck}>
              {comuns.map((mod) => (
                <ModalidadeCard key={mod.lote_chave} marketplace={atual} modalidade={mod} aba={aba} onAbrir={abrirEscopo} />
              ))}
            </Banda>
          )}
        </>
      )}
    </div>
  );
}
