import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { imprimirPapeisDePedido } from '@/lib/papeisDePedido';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Loader2,
  Printer,
  Receipt,
  XCircle,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

// As acoes que o responsavel executa sobre um lote, na ordem em que a fabrica
// as executa: conferir/imprimir os papeis, emitir as notas, e — quando a
// emissao precisa ser feita a mao no Bling — copiar os IDs de origem.
//
// O componente nunca recebe a lista de pedidos: recebe a CHAVE do lote
// (`params`), que e ou `{ demanda_id }` ou o seletor do escopo. Quem resolve o
// conjunto e o servidor, nas mesmas RPCs que desenharam a tela. Passar ids pela
// URL era a alternativa obvia e e justamente a que deixa a acao agir sobre um
// conjunto diferente do que esta na tela assim que qualquer coisa muda.

function paramsParaQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([chave, valor]) => {
    if (valor === null || valor === undefined || valor === '') return;
    if (Array.isArray(valor)) valor.forEach((v) => query.append(chave, v));
    else query.set(chave, valor);
  });
  return query;
}

export default function AcoesDoLote({ params, titulo = 'Ações do lote', className = '', mostrarIds = true, acoesExtras = null }) {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [imprimindo, setImprimindo] = useState(false);
  const [emitindo, setEmitindo] = useState(false);
  const [resultadosNf, setResultadosNf] = useState([]);
  const fonteNf = useRef(null);

  // `params` costuma ser um literal recriado a cada render; sem estabilizar,
  // o efeito abaixo dispararia em loop.
  const chave = useMemo(() => paramsParaQuery(params).toString(), [params]);

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro(null);
    try {
      const res = await fetch(`/api/v2/despacho/acoes?${chave}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar as ações do lote');
      setDados(json.data);
    } catch (err) {
      setErro(err.message || 'Não foi possível carregar as ações do lote.');
    } finally {
      setCarregando(false);
    }
  }, [chave]);

  useEffect(() => { carregar(); }, [carregar]);

  useEffect(() => () => { fonteNf.current?.close(); }, []);

  const imprimir = async () => {
    const ids = dados?.pedido_ids || [];
    if (ids.length === 0) {
      toast.warning('Nenhum pedido neste lote para imprimir.');
      return;
    }
    setImprimindo(true);
    try {
      const { total, blocked } = await imprimirPapeisDePedido(ids);
      if (total === 0) {
        toast.warning('Nenhum papel pôde ser montado — os pedidos ainda não têm número no ERP.');
      } else if (blocked.length > 0) {
        toast.warning(`${total} papéis enviados para impressão. ${blocked.length} ficaram de fora por falta de dados.`);
      } else {
        toast.success(`${total} papéis enviados para impressão.`);
      }
    } catch (err) {
      toast.error(err.message || 'Erro ao imprimir os papéis dos pedidos.');
    } finally {
      setImprimindo(false);
    }
  };

  const emitirNotas = (erpIntegrationId) => {
    if (!dados?.total) {
      toast.warning('Nenhum pedido neste lote.');
      return;
    }
    fonteNf.current?.close();
    setResultadosNf([]);
    setEmitindo(true);

    const query = paramsParaQuery(params);
    if (erpIntegrationId) query.set('erp_integration_id', erpIntegrationId);

    const fonte = new EventSource(`/api/v2/despacho/nfe?${query.toString()}`);
    fonteNf.current = fonte;

    fonte.onmessage = (evento) => {
      const dado = JSON.parse(evento.data);
      if (dado.status === 'complete') {
        fonte.close();
        setEmitindo(false);
        if (dado.fora_da_conta > 0) {
          toast.warning(
            `Emissão concluída. ${dado.fora_da_conta} pedido${dado.fora_da_conta > 1 ? 's' : ''} ` +
            'do lote não pertence a esta conta e ficou de fora.'
          );
        } else {
          toast.success('Emissão de notas concluída.');
        }
        // Emitir NF muda a situacao no marketplace: o lote encolhe.
        carregar();
        return;
      }
      setResultadosNf((anteriores) => [...anteriores, dado]);
    };

    fonte.onerror = () => {
      fonte.close();
      setEmitindo(false);
      toast.error('A conexão com o servidor de notas caiu.');
    };
  };

  const copiar = async (texto, rotulo) => {
    try {
      await navigator.clipboard.writeText(texto);
      toast.success(`${rotulo} copiado.`);
    } catch {
      toast.error('Não foi possível copiar. Selecione o texto e copie manualmente.');
    }
  };

  const contas = dados?.contas_erp || [];
  const semErp = dados?.sem_erp || [];
  const blocos = dados?.blocos_ids || [];
  const emitidas = resultadosNf.filter((r) => r.success).length;
  const falhas = resultadosNf.filter((r) => !r.success).length;

  if (erro) {
    return (
      <Card className={`border-destructive/50 ${className}`}>
        <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardContent className="space-y-4 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium">{titulo}</div>
            <div className="text-xs text-muted-foreground">
              {carregando ? 'carregando…' : `${dados?.total ?? 0} pedidos`}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {acoesExtras}
            <Button variant="outline" size="sm" className="gap-2" onClick={imprimir}
              disabled={carregando || imprimindo || !dados?.total}>
              {imprimindo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Printer className="h-4 w-4" />}
              Imprimir papéis
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="gap-2"
                  disabled={carregando || emitindo || contas.length === 0}>
                  {emitindo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                  Emitir notas
                  <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuItem onClick={() => emitirNotas(null)}>
                  <div>
                    <div className="text-sm">Pela conta de cada pedido</div>
                    <div className="text-xs text-muted-foreground">
                      {contas.length === 1
                        ? contas[0].conta
                        : `${contas.length} contas envolvidas neste lote`}
                    </div>
                  </div>
                </DropdownMenuItem>
                {contas.length > 0 && <DropdownMenuSeparator />}
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                  Ou emita só o que é de uma conta
                </DropdownMenuLabel>
                {/* Escolher uma conta recorta o lote, não reatribui o pedido: o
                    número do pedido no ERP só existe dentro da conta que o criou. */}
                {contas.map((conta) => (
                  <DropdownMenuItem key={conta.erp_integration_id}
                    onClick={() => emitirNotas(conta.erp_integration_id)}>
                    <div>
                      <div className="text-sm">{conta.conta}</div>
                      <div className="text-xs text-muted-foreground">{conta.total} pedidos nesta conta</div>
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {semErp.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              {semErp.length} pedido{semErp.length > 1 ? 's' : ''} ainda sem número no ERP.
              {' '}A nota destes não sai por aqui, e o papel deles também não é impresso.
              <div className="mt-1 font-mono">
                {semErp.slice(0, 8).map((p) => p.id_origem || p.pedido_id).join(', ')}
                {semErp.length > 8 && ` e mais ${semErp.length - 8}`}
              </div>
            </div>
          </div>
        )}

        {mostrarIds && blocos.length > 0 && (
          <div className="space-y-2 rounded-md border bg-muted/30 p-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium">
                IDs de origem para busca no Bling
                <span className="ml-2 font-normal text-muted-foreground">
                  {blocos.length > 1
                    ? `${blocos.length} blocos de até ${dados.tamanho_bloco}`
                    : `${blocos[0].quantidade} pedidos`}
                </span>
              </div>
              {blocos.length > 1 && (
                <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs"
                  onClick={() => copiar(blocos.map((b) => b.texto).join(';'), 'Lista completa')}>
                  <Copy className="h-3 w-3" /> Copiar tudo
                </Button>
              )}
            </div>
            {blocos.map((bloco) => (
              <div key={bloco.indice} className="flex items-center gap-2">
                {blocos.length > 1 && (
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">
                    {bloco.indice}/{blocos.length}
                  </span>
                )}
                <Input readOnly value={bloco.texto} className="h-8 font-mono text-xs" />
                <Button variant="outline" size="icon" className="h-8 w-8 shrink-0"
                  title={`Copiar ${bloco.quantidade} IDs`}
                  onClick={() => copiar(bloco.texto, `${bloco.quantidade} IDs`)}>
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {resultadosNf.length > 0 && (
          <div className="space-y-2 rounded-md border p-3">
            <div className="flex items-center gap-2 text-xs">
              <span className="font-medium">Emissão de notas</span>
              {emitidas > 0 && (
                <Badge variant="outline" className="border-emerald-500 text-emerald-700">
                  {emitidas} emitidas
                </Badge>
              )}
              {falhas > 0 && (
                <Badge variant="outline" className="border-destructive text-destructive">
                  {falhas} com erro
                </Badge>
              )}
            </div>
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {resultadosNf.map((resultado, indice) => (
                <div key={indice} className="flex items-start gap-2 text-xs">
                  {resultado.success
                    ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                    : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />}
                  <span className="font-mono">{resultado.order?.numeroLoja || resultado.order?.numero || '—'}</span>
                  {!resultado.success && (
                    <span className="text-destructive">{resultado.error}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
