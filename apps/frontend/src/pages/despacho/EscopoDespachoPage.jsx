import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { TooltipProvider } from '@/components/ui/tooltip';
import PacoteBadge from '@/components/pedidos/PacoteBadge';
import AcoesDoLote from '@/components/despacho/AcoesDoLote';
import ConferenciaDoArquivo from '@/components/despacho/ConferenciaDoArquivo';
import LinhasConsolidadas from '@/components/despacho/LinhasConsolidadas';
import { ajusteDaLinha, aplicarAjustes, resumoDaLista } from '@/lib/ajustesConsolidacao';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { AlertTriangle, ArrowLeft, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

// Escopo de despacho — N1 da navegacao por contexto.
// Contrato: docs/specs/02-domains/despacho/spec.md, "Escopo composto e lancamento"
//
// O escopo e (no, horizonte) ou o recorte de uma conferencia de arquivo. Nao ha
// checkbox por pedido no fluxo normal: a lista e para conferencia contra o
// painel do marketplace, nao para selecao.
//
// A TELA E UMA SO. Clicar num card da torre ja mostra o lote consolidado —
// produtos agregados, miolo identificado, ordem de producao — junto das tres
// acoes de fabrica (papeis, notas, IDs) e do botao de publicar.
//
// Antes havia um passo intermediario: um botao "Consolidar N pedidos" que
// criava um RASCUNHO no banco, e so depois dele a consolidacao aparecia. Esse
// passo prometia deixar o operador conferir antes de fechar o lote, mas fazia o
// contrario: ele tinha que escrever no banco para poder conferir, e a partir
// dali "desfazer" significava cancelar demanda. Como a consolidacao nao depende
// de gravar nada — sai da mesma RPC, chamada sem efeito colateral — o passo so
// adiantava a escrita.
//
// Hoje a demanda nasce no clique de publicar, que e o unico momento em que
// despachado_em e carimbado e o galpao assume o lote.

// A escada de prazo. `sem_prazo` NAO entra aqui: ele e um toggle proprio.
// Como escada, incluir um pedido sem prazo obrigaria a arrastar ate o ultimo
// degrau e levar junto amanha e depois — a escolha entre esquecer o pedido ou
// inchar o lote. Prazo desconhecido ja e tratado como a hipotese mais urgente
// na arvore; aqui o lancamento concorda com ela.
const HORIZONTE_STEPS = ['atrasado', 'hoje', 'amanha', 'depois'];
const HORIZONTE_LABEL = {
  atrasado: 'Atrasado',
  hoje: 'Hoje',
  amanha: 'Amanhã',
  depois: 'Depois',
  sem_prazo: 'Sem prazo',
};

const ABA_PARA_DEGRAU = { hoje: 1, amanha: 2, proximos: 3 };

function parseIntOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = parseInt(value, 10);
  return Number.isNaN(n) ? null : n;
}

// A consolidacao do lote, sem gravar nada.
//
// Chama /despacho/previsao, que roda a MESMA RPC que o lancamento usa para
// materializar os itens (`despacho_materializar_itens` ->
// `despacho_consolidar_pedidos`). E por isso que o que esta na tela e o que
// vai para producao: nao existe uma segunda consolidacao para divergir.
function PreviaConsolidacao({ params, ajustes, onAjustesChange }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [carregando, setCarregando] = useState(true);

  // `params` costuma ser um literal recriado a cada render; sem estabilizar, o
  // efeito abaixo dispararia em laco.
  const chave = useMemo(() => {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([nome, valor]) => {
      if (valor === null || valor === undefined || valor === '') return;
      if (Array.isArray(valor)) valor.forEach((v) => query.append(nome, v));
      else query.set(nome, valor);
    });
    return query.toString();
  }, [params]);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    setErro(null);
    (async () => {
      try {
        const res = await fetch(`/api/v2/despacho/previsao?${chave}`);
        const json = await res.json();
        if (!json.success) throw new Error(json.error || 'Falha ao montar a consolidação');
        if (vivo) setDados(json.data);
      } catch (err) {
        if (vivo) setErro(err.message);
      } finally {
        if (vivo) setCarregando(false);
      }
    })();
    return () => { vivo = false; };
  }, [chave]);

  // O escopo mudou de baixo dos ajustes (o operador trocou o horizonte, por
  // exemplo): manter ajustes que apontam para linhas de outro lote produziria
  // um erro no lançamento. Some com eles.
  useEffect(() => { onAjustesChange([]); }, [chave, onAjustesChange]);

  const itensAjustados = useMemo(
    () => aplicarAjustes(dados?.itens || [], ajustes),
    [dados, ajustes]
  );

  const registrar = ({ op, linha, valor }) => {
    onAjustesChange([...ajustes, ajusteDaLinha(op, linha, op === 'quantidade' ? { valor } : {})]);
  };

  return (
    <LinhasConsolidadas
      itens={itensAjustados}
      resumo={ajustes.length ? resumoDaLista(itensAjustados) : dados}
      titulo="Consolidação do lote"
      ajuda="o que este lote vai produzir — corrija o que faltar antes de publicar"
      carregando={carregando}
      erro={erro}
      onAjustar={registrar}
      totalAjustes={ajustes.length}
      onDesfazerAjustes={() => onAjustesChange([])}
    />
  );
}

export default function EscopoDespachoPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useSecaoSidebar();

  const integrationId = parseIntOrNull(searchParams.get('integration_id'));
  const conferenciaId = parseIntOrNull(searchParams.get('conferencia_id'));
  const origemArquivo = conferenciaId !== null;
  // O escopo e o LOTE: um ou mais canais que compartilham a janela.
  const modalidadeIds = useMemo(() => {
    const lista = searchParams.getAll('modalidade_ids').map(parseIntOrNull).filter((v) => v !== null);
    if (lista.length) return lista;
    const unico = parseIntOrNull(searchParams.get('modalidade_id'));
    return unico !== null ? [unico] : [];
  }, [searchParams]);
  const marketplaceNome = searchParams.get('marketplace_nome') || 'Origem não resolvida';
  const modalidadeNome = searchParams.get('modalidade_nome') || 'Modalidade não classificada';
  const abaOrigem = searchParams.get('aba') || 'hoje';

  // Abre coerente com a aba clicada na torre: a aba Hoje já inclui atrasados e
  // pedidos sem prazo, então o escopo abre do mesmo jeito.
  const [horizonteAte, setHorizonteAte] = useState(ABA_PARA_DEGRAU[abaOrigem] ?? 1);
  const [incluirSemPrazo, setIncluirSemPrazo] = useState(abaOrigem === 'hoje');
  const [dados, setDados] = useState(null);
  const [loading, setLoading] = useState(true);
  const [publicando, setPublicando] = useState(false);
  const [conflitos, setConflitos] = useState([]);
  const [erro, setErro] = useState(null);
  // Os ajustes da prévia vivem aqui, e não dentro dela, porque quem publica é
  // esta página: é ela que precisa enviá-los junto com o lançamento.
  const [ajustes, setAjustes] = useState([]);
  const aplicarAjustesNaPrevia = useCallback((novos) => setAjustes(novos), []);

  const horizonte = useMemo(() => {
    const passos = HORIZONTE_STEPS.slice(0, horizonteAte + 1);
    return incluirSemPrazo ? [...passos, 'sem_prazo'] : passos;
  }, [horizonteAte, incluirSemPrazo]);

  // A chave do lote — nao a lista de pedidos. As acoes (papeis, notas, IDs) e a
  // consolidacao pedem ao servidor o mesmo conjunto que desenhou esta tela;
  // mandar ids pela URL faria a acao agir sobre um conjunto diferente do
  // exibido assim que qualquer coisa mudasse no banco, e estouraria o limite de
  // URL num lote grande.
  const chaveDoEscopo = useMemo(() => (
    origemArquivo
      ? { conferencia_id: conferenciaId }
      : {
          integration_id: integrationId ?? undefined,
          modalidade_ids: modalidadeIds,
          modalidade_id: modalidadeIds[0] ?? undefined,
          horizonte,
          data: dataOperacionalHoje(),
        }
  ), [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte]);

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const params = new URLSearchParams();
      if (origemArquivo) {
        params.set('conferencia_id', conferenciaId);
      } else {
        if (integrationId !== null) params.set('integration_id', integrationId);
        modalidadeIds.forEach((id) => params.append('modalidade_ids', id));
        // Compatibilidade com API que ainda nao conhece lotes: sem isso ela le
        // modalidade_id como nulo e a lista de pedidos volta vazia.
        if (modalidadeIds.length > 0) params.set('modalidade_id', modalidadeIds[0]);
        horizonte.forEach((h) => params.append('horizonte', h));
        params.set('data', dataOperacionalHoje());
      }

      const res = await fetch(`/api/v2/despacho/escopo?${params.toString()}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar o escopo');
      setDados(json.data);
    } catch (err) {
      setErro(err.message || 'Não foi possível carregar o escopo.');
    } finally {
      setLoading(false);
    }
  }, [origemArquivo, conferenciaId, integrationId, modalidadeIds, horizonte]);

  useEffect(() => { carregar(); }, [carregar]);

  // Publicar e o unico botao desta tela que escreve.
  //
  // A demanda continua nascendo de `despacho_lancar_*`: ela e criada aqui, um
  // instante antes de ser publicada, e nao por um clique separado. Se o
  // lancamento passar e a publicacao falhar, o rascunho fica aberto e a proxima
  // tentativa SOMA nele em vez de criar um segundo lote — por isso a sequencia
  // e segura para repetir.
  const publicar = async () => {
    setPublicando(true);
    setConflitos([]);
    try {
      const lancamento = await fetch('/api/v2/despacho/lancar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          integration_id: integrationId,
          modalidade_ids: modalidadeIds,
          modalidade_id: modalidadeIds[0] ?? null,
          horizonte,
          data: dataOperacionalHoje(),
          ...(ajustes.length ? { ajustes } : {}),
          ...(origemArquivo ? { conferencia_id: conferenciaId } : {}),
        }),
      });
      const criado = await lancamento.json();
      if (!criado.success) throw new Error(criado.error || 'Não foi possível montar a demanda');

      const jaEmRascunho = criado.data.ja_em_rascunho || [];
      if (jaEmRascunho.length > 0) setConflitos(jaEmRascunho);

      const res = await fetch('/api/v2/despacho/publicar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ demanda_id: criado.data.demanda_id }),
      });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Não foi possível publicar');

      toast.success(
        `${json.data.demanda_codigo} publicada — ${json.data.total_pedidos} pedidos foram para produção`
      );
      navigate('/despacho');
    } catch (err) {
      toast.error(err.message || 'Não foi possível publicar a demanda');
    } finally {
      setPublicando(false);
    }
  };

  const total = dados?.total ?? 0;
  const totalNo = dados?.total_no ?? total;
  const foraDoHorizonte = Math.max(0, totalNo - total);
  const qtdSemPrazo = dados?.buckets?.sem_prazo ?? 0;

  return (
    <div className="p-6">
      <button
        type="button"
        onClick={() => navigate('/despacho')}
        className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Voltar para a torre de despacho
      </button>

      <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        {origemArquivo && (
          <>
            <span>📄 conferência de arquivo</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </>
        )}
        <span>{marketplaceNome}</span>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">{modalidadeNome}</span>
      </div>

      {/* A procedência do lote. No lote vindo da torre ela está no par
          (marketplace, modalidade) do cabeçalho; no lote vindo de planilha ela
          é o arquivo e o filtro, e traz junto as duas ações que só existem
          nessa origem: criar o que a base não tem e buscar o número no ERP. */}
      {origemArquivo && (
        <ConferenciaDoArquivo conferenciaId={conferenciaId} onMudou={carregar} />
      )}

      {/* O horizonte define o escopo, então ele continua no topo. No lote vindo
          de arquivo o recorte já foi decidido pelo filtro da planilha, e um
          segundo seletor aqui abriria caminho para os dois discordarem. */}
      {!origemArquivo && (
        <Card className="mb-6">
          <CardContent className="py-5">
            <div className="mb-3 text-sm font-medium">Horizonte</div>
            <div className="flex flex-wrap gap-2">
              {HORIZONTE_STEPS.map((step, idx) => {
                const qtd = dados?.buckets?.[step] ?? 0;
                return (
                  <button
                    key={step}
                    type="button"
                    onClick={() => setHorizonteAte(idx)}
                    className={
                      'rounded-full border px-3 py-1 text-xs transition-colors ' +
                      (idx <= horizonteAte
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:border-primary/40')
                    }
                  >
                    até {HORIZONTE_LABEL[step]}
                    {qtd > 0 && <span className="ml-1.5 opacity-70">{qtd}</span>}
                  </button>
                );
              })}

              {/* Toggle próprio, fora da escada: um Flex sem prazo não deve
                  exigir que o operador leve junto todo o futuro. */}
              {qtdSemPrazo > 0 && (
                <button
                  type="button"
                  onClick={() => setIncluirSemPrazo((v) => !v)}
                  className={
                    'ml-2 rounded-full border px-3 py-1 text-xs transition-colors ' +
                    (incluirSemPrazo
                      ? 'border-amber-500 bg-amber-100 text-amber-800'
                      : 'border-border text-muted-foreground hover:border-amber-400')
                  }
                >
                  + Sem prazo <span className="ml-1.5 opacity-70">{qtdSemPrazo}</span>
                </button>
              )}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Compare o total abaixo com a tela do marketplace antes de publicar.
            </p>
            {foraDoHorizonte > 0 && (
              <p className="mt-1 text-xs text-amber-700">
                {foraDoHorizonte} pedido{foraDoHorizonte > 1 ? 's' : ''} deste card
                {foraDoHorizonte > 1 ? ' estão' : ' está'} fora do horizonte selecionado.
                O card da torre mostra {totalNo}.
              </p>
            )}
            {!incluirSemPrazo && qtdSemPrazo > 0 && (
              <p className="mt-1 flex items-center gap-1 text-xs text-amber-700">
                <AlertTriangle className="h-3 w-3" />
                {qtdSemPrazo} pedido{qtdSemPrazo > 1 ? 's' : ''} sem prazo informado
                {qtdSemPrazo > 1 ? ' ficam' : ' fica'} de fora. Prazo desconhecido costuma ser o mais urgente.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {erro && (
        <Card className="mb-4 border-destructive/50">
          <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardContent className="py-5">
          <div className="text-3xl font-semibold leading-none">
            {loading ? '—' : total}
            {!loading && foraDoHorizonte > 0 && (
              <span className="ml-2 align-middle text-base font-normal text-muted-foreground">
                de {totalNo}
              </span>
            )}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            pedidos neste lote · confira contra o painel do marketplace
          </div>
        </CardContent>
      </Card>

      {/* A consolidação, direto — sem passar por criar rascunho. */}
      {!loading && total > 0 && (
        <PreviaConsolidacao
          params={chaveDoEscopo}
          ajustes={ajustes}
          onAjustesChange={aplicarAjustesNaPrevia}
        />
      )}

      {/* A ordem dos blocos é a ordem da fábrica: conferir a produção, emitir
          as notas, imprimir os papéis e só então publicar. Publicar antes de
          emitir a nota entrega ao galpão um lote que a expedição ainda não
          pode despachar. */}
      {!loading && total > 0 && (
        <AcoesDoLote
          className="mb-6"
          params={chaveDoEscopo}
          titulo="Notas fiscais e papéis"
        />
      )}

      {conflitos.length > 0 && (
        <Card className="mb-6 border-amber-400 bg-amber-50/60">
          <CardContent className="py-4 text-sm text-amber-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">
                  {conflitos.length} pedido{conflitos.length > 1 ? 's' : ''}
                  {conflitos.length > 1 ? ' já estavam' : ' já estava'} em outra consolidação
                  aberta e ficou de fora.
                </div>
                <div className="mt-1 text-xs">
                  {[...new Set(conflitos.map((c) => c.demanda_codigo))].join(', ')}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && total > 0 && (
        <Card className="mb-6 border-slate-900">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div>
              <div className="text-sm font-medium">Publicar a demanda de produção</div>
              <div className="mt-1 text-xs text-muted-foreground">
                A partir daqui o galpão assume o lote e os {total} pedidos saem da torre.
              </div>
            </div>
            <Button size="lg" onClick={publicar} disabled={publicando}>
              {publicando ? 'Publicando…' : `Publicar ${total} pedidos`}
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="mb-2 text-sm font-medium">Pedidos no lote</div>
      {loading && (
        <div className="space-y-2">
          <div className="h-10 w-full animate-pulse rounded-md bg-muted" />
          <div className="h-10 w-full animate-pulse rounded-md bg-muted" />
        </div>
      )}

      {!loading && dados?.pedidos?.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Nenhum pedido neste escopo.
          </CardContent>
        </Card>
      )}

      {!loading && dados?.pedidos?.length > 0 && (
        <TooltipProvider>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Pedido</th>
                  {/* O numero do ERP serve ao galpao; este e o numero que o
                      operador confere contra o painel do marketplace. */}
                  <th className="px-3 py-2 font-medium">ID no marketplace</th>
                  <th className="px-3 py-2 font-medium">Cliente</th>
                  <th className="px-3 py-2 font-medium">Total</th>
                  <th className="px-3 py-2 font-medium">Prazo</th>
                  <th className="px-3 py-2 font-medium">Método de envio</th>
                </tr>
              </thead>
              <tbody>
                {dados.pedidos.map((pedido) => (
                  <tr key={pedido.id} className="border-t">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span>{pedido.numero_pedido || pedido.codigo_pedido_externo}</span>
                        {/* Irmãos de pacote compartilham numero_pedido. Sem o
                            marcador, as duas linhas parecem duplicata — e a
                            reação a uma duplicata, momentos antes de publicar
                            produção, é remover uma delas. */}
                        <PacoteBadge
                          variant="inline"
                          irmaos={pedido.pack_irmaos}
                          irmaosIds={pedido.pack_irmaos_ids}
                        />
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {pedido.marketplace_order_id || pedido.codigo_pedido_externo || '—'}
                    </td>
                    <td className="px-3 py-2">{pedido.cliente_nome || '—'}</td>
                    <td className="px-3 py-2">
                      {pedido.total_pedido != null
                        ? Number(pedido.total_pedido).toLocaleString('pt-BR', {
                            style: 'currency', currency: 'BRL',
                          })
                        : '—'}
                    </td>
                    <td className="px-3 py-2">
                      {pedido.data_limite_envio
                        ? new Date(pedido.data_limite_envio).toLocaleDateString('pt-BR')
                        : 'não informado'}
                    </td>
                    <td className="px-3 py-2">
                      {pedido.metodo_envio_rotulo ? (
                        pedido.metodo_envio_rotulo
                      ) : (
                        <Badge variant="outline" className="border-amber-400 text-[10px] text-amber-700">
                          não classificado
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TooltipProvider>
      )}
    </div>
  );
}
