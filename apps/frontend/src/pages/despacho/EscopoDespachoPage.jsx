import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { TooltipProvider } from '@/components/ui/tooltip';
import PacoteBadge from '@/components/pedidos/PacoteBadge';
import AcoesDoLote from '@/components/despacho/AcoesDoLote';
import { dataOperacionalHoje } from '@/lib/dataOperacional';
import { useSecaoSidebar } from '@/lib/hooks/useSecaoSidebar';
import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight, FileText, Package } from 'lucide-react';
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

// Escopo de despacho — N1 da navegacao por contexto.
// Contrato: docs/specs/02-domains/despacho/spec.md, "Escopo composto e lancamento"
//
// O escopo e (no, horizonte). Nao ha checkbox por pedido no fluxo normal: a
// lista e para conferencia contra o painel do marketplace, nao para selecao.
//
// O fluxo tem quatro passos, na ordem em que a fabrica os executa:
//   consolidar -> emitir notas -> imprimir papeis -> publicar demanda
// Os tres primeiros acontecem com o lote ja fechado e ainda na torre; publicar
// e o unico momento em que despachado_em e carimbado, ou seja, o momento em
// que o galpao assume o lote e os pedidos saem da torre.
//
// O passo intermediario chama-se CONSOLIDACAO, nunca "rascunho". No banco o
// status continua sendo RASCUNHO — mudar isso arrastaria RPCs, historico e
// nome de coluna sem ganhar nada — mas "rascunho" na tela dizia ao operador
// que aquilo era um esboco descartavel, quando na verdade e o lote fechado
// sobre o qual ele vai emitir nota fiscal.

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

function LinhasProducao({ demandaId }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const res = await fetch(`/api/v2/despacho/demanda/${demandaId}/itens`);
        const json = await res.json();
        if (!json.success) throw new Error(json.error || 'Falha ao carregar as linhas de produção');
        if (vivo) setDados(json.data);
      } catch (err) {
        if (vivo) setErro(err.message);
      }
    })();
    return () => { vivo = false; };
  }, [demandaId]);

  if (erro) {
    return (
      <Card className="mb-6 border-destructive/50">
        <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
      </Card>
    );
  }
  if (!dados) {
    return <div className="mb-6 h-32 w-full animate-pulse rounded-md bg-muted" />;
  }

  const itens = dados.itens || [];
  // Agrupa por miolo preservando a ordem que veio do banco. A ordem É a
  // informação: miolo por carga decrescente e, dentro dele, quantidade
  // decrescente — a mesma da planilha do legado.
  const grupos = [];
  for (const item of itens) {
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.chave === item.miolo_chave) ultimo.itens.push(item);
    else grupos.push({ chave: item.miolo_chave, rotulo: item.miolo_nome, itens: [item] });
  }

  return (
    <>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium">Ordem de produção</span>
        <span className="text-xs text-muted-foreground">miolo com mais carga primeiro</span>
        <span className="ml-auto text-xs text-muted-foreground">
          <FileText className="mr-1 inline h-3.5 w-3.5" />
          {dados.demanda?.demanda_id} · {itens.length} linhas ·{' '}
          {Math.round(dados.total_pecas)} peças · {grupos.length}{' '}
          {grupos.length === 1 ? 'miolo' : 'miolos'}
        </span>
      </div>
      {dados.sem_estoque > 0 && (
        <div className="mb-2 text-xs text-muted-foreground">
          {dados.sem_estoque} {dados.sem_estoque === 1 ? 'linha produz' : 'linhas produzem'} sem
          movimentar estoque (SKU sem produto interno vinculado)
        </div>
      )}

      <div className="mb-6 overflow-hidden rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="w-10 px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Produto</th>
              <th className="px-3 py-2 font-medium">Variação</th>
              <th className="px-3 py-2 font-medium">SKU</th>
              <th className="w-20 px-3 py-2 text-right font-medium">Qtde</th>
            </tr>
          </thead>
          <tbody>
            {grupos.map((grupo) => {
              const carga = grupo.itens.reduce((s, i) => s + Number(i.quantidade || 0), 0);
              const viaBom = grupo.itens[0]?.miolo_origem === 'BOM';
              return (
                <Fragment key={grupo.chave}>
                  <tr className="border-t bg-muted/30">
                    <td colSpan={4} className="px-3 py-1.5 text-xs font-semibold">
                      <span className="inline-flex items-center gap-1.5">
                        <Package className="h-3.5 w-3.5" />
                        Miolo {grupo.rotulo}
                        {viaBom && (
                          <Badge variant="outline" className="text-[9px]">via ficha técnica</Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right text-xs font-semibold tabular-nums">
                      {Math.round(carga)}
                    </td>
                  </tr>
                  {grupo.itens.map((item) => (
                    <tr key={item.id} className="border-t">
                      <td className="px-3 py-2 text-xs tabular-nums text-muted-foreground">
                        {item.ordem}
                      </td>
                      <td className="px-3 py-2">{item.descricao}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.variacao && item.variacao !== '-' ? item.variacao : '—'}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                        {item.sku_externo}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {Math.round(Number(item.quantidade || 0))}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function EscopoDespachoPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  useSecaoSidebar();

  const integrationId = parseIntOrNull(searchParams.get('integration_id'));
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
  const [lancando, setLancando] = useState(false);
  const [publicando, setPublicando] = useState(false);
  const [rascunho, setRascunho] = useState(null);
  const [erro, setErro] = useState(null);

  const horizonte = useMemo(() => {
    const passos = HORIZONTE_STEPS.slice(0, horizonteAte + 1);
    return incluirSemPrazo ? [...passos, 'sem_prazo'] : passos;
  }, [horizonteAte, incluirSemPrazo]);

  // A chave do lote — nao a lista de pedidos. As acoes (papeis, notas, IDs)
  // pedem ao servidor o mesmo conjunto que desenhou esta tela; mandar ids pela
  // URL faria a acao agir sobre um conjunto diferente do exibido assim que
  // qualquer coisa mudasse no banco, e estouraria o limite de URL num lote
  // grande.
  const chaveDoEscopo = useMemo(() => ({
    integration_id: integrationId ?? undefined,
    modalidade_ids: modalidadeIds,
    modalidade_id: modalidadeIds[0] ?? undefined,
    horizonte,
    data: dataOperacionalHoje(),
  }), [integrationId, modalidadeIds, horizonte]);

  const chaveDoRascunho = useMemo(
    () => (rascunho ? { demanda_id: rascunho.id } : null),
    [rascunho]
  );

  const carregar = useCallback(async () => {
    setLoading(true);
    setErro(null);
    try {
      const hoje = dataOperacionalHoje();
      const params = new URLSearchParams();
      if (integrationId !== null) params.set('integration_id', integrationId);
      modalidadeIds.forEach((id) => params.append('modalidade_ids', id));
      // Compatibilidade com API que ainda nao conhece lotes: sem isso ela le
      // modalidade_id como nulo e a lista de pedidos volta vazia.
      if (modalidadeIds.length > 0) params.set('modalidade_id', modalidadeIds[0]);
      horizonte.forEach((h) => params.append('horizonte', h));
      params.set('data', hoje);

      const res = await fetch(`/api/v2/despacho/escopo?${params.toString()}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar o escopo');
      setDados(json.data);
    } catch (err) {
      setErro(err.message || 'Não foi possível carregar o escopo.');
    } finally {
      setLoading(false);
    }
  }, [integrationId, modalidadeIds, horizonte]);

  useEffect(() => {
    if (!rascunho) carregar();
  }, [carregar, rascunho]);

  const consolidar = async () => {
    setLancando(true);
    try {
      const hoje = dataOperacionalHoje();
      const res = await fetch('/api/v2/despacho/lancar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          integration_id: integrationId,
          modalidade_ids: modalidadeIds,
          modalidade_id: modalidadeIds[0] ?? null,
          horizonte,
          data: hoje,
        }),
      });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Não foi possível consolidar os pedidos');

      const { demanda_id, demanda_codigo, total_pedidos, somou_em_rascunho } = json.data;
      setRascunho({ id: demanda_id, codigo: demanda_codigo, totalPedidos: total_pedidos });
      toast.success(
        somou_em_rascunho
          ? `Pedidos somados à consolidação ${demanda_codigo} — agora com ${total_pedidos}`
          : `Consolidação ${demanda_codigo} fechada com ${total_pedidos} pedidos`
      );
    } catch (err) {
      toast.error(err.message || 'Não foi possível consolidar os pedidos');
    } finally {
      setLancando(false);
    }
  };

  const publicar = async () => {
    setPublicando(true);
    try {
      const res = await fetch('/api/v2/despacho/publicar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ demanda_id: rascunho.id }),
      });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Não foi possível publicar');
      toast.success(
        `${json.data.demanda_codigo} publicada — ${json.data.total_pedidos} pedidos foram para produção`
      );
      navigate('/despacho');
    } catch (err) {
      toast.error(err.message || 'Não foi possível publicar');
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
        <span>{marketplaceNome}</span>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="font-medium text-foreground">{modalidadeNome}</span>
      </div>

      {rascunho ? (
        <>
          <Card className="mb-4 border-emerald-600/40 bg-emerald-50/50">
            <CardContent className="flex items-start gap-2 py-4 text-sm">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
              <div>
                <div className="font-medium text-emerald-900">
                  Consolidação {rascunho.codigo} fechada com {rascunho.totalPedidos} pedidos.
                </div>
                <div className="text-emerald-800">
                  Os pedidos continuam na torre até você publicar.
                </div>
              </div>
            </CardContent>
          </Card>

          {/* A ordem dos blocos é a ordem da fábrica: emitir as notas, imprimir
              os papéis, conferir a produção e só então publicar. Enquanto o
              botão de publicar ficava no topo, ele era a primeira coisa
              clicável da tela — e publicar antes de emitir a nota entrega ao
              galpão um lote que a expedição ainda não pode despachar. */}
          {chaveDoRascunho && (
            <AcoesDoLote
              className="mb-6"
              params={chaveDoRascunho}
              titulo="1. Notas fiscais e papéis desta consolidação"
            />
          )}

          <div className="mb-2 text-sm font-medium">2. Confira a produção</div>
          <LinhasProducao demandaId={rascunho.id} />

          <Card className="mb-6 border-slate-900">
            <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
              <div>
                <div className="text-sm font-medium">3. Publicar a demanda de produção</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  A partir daqui o galpão assume o lote e os {rascunho.totalPedidos} pedidos saem da torre.
                </div>
              </div>
              <Button size="lg" onClick={publicar} disabled={publicando}>
                {publicando ? 'Publicando…' : 'Publicar demanda'}
              </Button>
            </CardContent>
          </Card>

          <button
            type="button"
            onClick={() => setRascunho(null)}
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            Desfazer e ajustar o horizonte
          </button>
        </>
      ) : (
        <>
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
                Compare o total abaixo com a tela do marketplace antes de montar o lote.
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

          {erro && (
            <Card className="mb-4 border-destructive/50">
              <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
            </Card>
          )}

          <Card className="mb-6">
            <CardContent className="flex items-center justify-between py-5">
              <div>
                <div className="text-3xl font-semibold leading-none">
                  {loading ? '—' : total}
                  {!loading && foraDoHorizonte > 0 && (
                    <span className="ml-2 align-middle text-base font-normal text-muted-foreground">
                      de {totalNo}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">pedidos no escopo selecionado</div>
              </div>
              <Button size="lg" disabled={loading || lancando || total === 0} onClick={consolidar}>
                {lancando ? 'Consolidando…' : `Consolidar ${total} pedidos`}
              </Button>
            </CardContent>
          </Card>

          {/* As mesmas acoes ficam disponiveis antes de consolidar, mas sobre o
              escopo — que e uma consulta viva, nao um lote fechado. O titulo
              diz isso: quem emite nota daqui esta emitindo sobre o que a torre
              enxerga agora, e um pedido pago um minuto depois entra no lote e
              nao na leva de notas. */}
          {!loading && total > 0 && (
            <AcoesDoLote
              className="mb-6"
              params={chaveDoEscopo}
              titulo="Ações sobre o escopo (o lote ainda não foi fechado)"
            />
          )}

          <div className="mb-2 text-sm font-medium">Pedidos no escopo</div>
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
              <div className="overflow-hidden rounded-md border">
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
                                reação a uma duplicata, momentos antes de lançar
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
        </>
      )}
    </div>
  );
}
