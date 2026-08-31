import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AlertTriangle, FileSpreadsheet, Loader2, Receipt } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

// De onde veio este lote, quando ele veio de uma planilha.
//
// Fica DENTRO da tela do escopo, e não numa tela anterior. A conferência não é
// um destino: é a procedência do lote — a mesma informação que, no lote vindo
// da torre, está no par (marketplace, modalidade) do cabeçalho. Enquanto ela
// morava numa tela própria, o operador subia o arquivo, via estatística e
// precisava de mais um clique para chegar onde queria desde o começo.
//
// O funil conta o DESCARTE por etapa, não o que sobrou. O operador não precisa
// saber quantas linhas passaram por cada filtro; precisa descobrir que escolheu
// o filtro errado — e isso aparece no tamanho do que foi jogado fora.

const ETAPA_LABEL = {
  modalidade: 'outra modalidade',
  ja_rastreado: 'já com rastreio',
  estado: 'estado não elegível',
  periodo: 'fora do período',
  filtro: 'descartado pelo filtro',
};

function Numero({ valor, rotulo, tom = '' }) {
  return (
    <div>
      <div className={'text-2xl font-semibold tabular-nums ' + tom}>{valor}</div>
      <div className="text-xs text-muted-foreground">{rotulo}</div>
    </div>
  );
}

export default function ConferenciaDoArquivo({ conferenciaId, onMudou }) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [trabalhando, setTrabalhando] = useState(null);

  const carregar = useCallback(async () => {
    try {
      const res = await fetch(`/api/v2/despacho/arquivo/${conferenciaId}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao carregar a conferência');
      setDados(json.data);
    } catch (err) {
      setErro(err.message);
    }
  }, [conferenciaId]);

  useEffect(() => { carregar(); }, [carregar]);

  const acao = async (endpoint) => {
    setTrabalhando(endpoint);
    try {
      const res = await fetch(`/api/v2/despacho/arquivo/${conferenciaId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'Falha ao executar a ação');

      const criados = json.data?.ingest?.criados?.length ?? 0;
      toast.success(
        endpoint === 'ingerir'
          ? `${criados} ${criados === 1 ? 'pedido criado' : 'pedidos criados'} a partir da planilha.`
          : 'Busca de número no ERP concluída.'
      );
      await carregar();
      // O lote mudou de tamanho: quem desenhou a tela precisa recarregar.
      onMudou?.();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setTrabalhando(null);
    }
  };

  if (erro) {
    return (
      <Card className="mb-6 border-destructive/50">
        <CardContent className="py-4 text-sm text-destructive">{erro}</CardContent>
      </Card>
    );
  }
  if (!dados) return <div className="mb-6 h-24 w-full animate-pulse rounded-md bg-muted" />;

  const funil = dados.funil || {};
  const descartados = funil.descartados || [];
  const naoEncontrados = dados.nao_encontrados || [];

  return (
    <Card className="mb-6">
      <CardContent className="space-y-4 py-5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">{dados.arquivo_nome}</span>
          <span className="text-xs text-muted-foreground">
            {funil.linhas} linhas lidas · {funil.refs} pedidos no filtro
          </span>
        </div>

        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Numero valor={funil.na_torre ?? 0} rotulo="pendentes na torre — este lote" tom="text-emerald-700" />
          <Numero valor={funil.casados ?? 0} rotulo="encontrados na base" />
          <Numero
            valor={funil.nao_encontrados ?? 0}
            rotulo="a base ainda não tem"
            tom={funil.nao_encontrados > 0 ? 'text-amber-700' : ''}
          />
          <Numero valor={funil.fora_da_torre ?? 0} rotulo="já fora da torre" />
        </div>

        {descartados.length > 0 && (
          <div className="text-xs text-muted-foreground">
            Descartado pelo filtro:{' '}
            {descartados
              .map((d) => `${d.qtd} ${ETAPA_LABEL[d.etapa] || d.etapa}`)
              .join(' · ')}
          </div>
        )}

        {naoEncontrados.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              {naoEncontrados.length}{' '}
              {naoEncontrados.length === 1
                ? 'pedido do arquivo não chegou'
                : 'pedidos do arquivo não chegaram'}{' '}
              na base pelo ID de origem — {naoEncontrados.length === 1 ? 'ele fica' : 'eles ficam'} de
              fora do lote até serem criados.
              <div className="mt-1 font-mono">
                {naoEncontrados.slice(0, 10).join(', ')}
                {naoEncontrados.length > 10 && ` e mais ${naoEncontrados.length - 10}`}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {naoEncontrados.length > 0 && (
            <Button
              size="sm"
              disabled={trabalhando !== null}
              onClick={() => acao('ingerir')}
              className="gap-2"
            >
              {trabalhando === 'ingerir' ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Criar {naoEncontrados.length} pedidos a partir da planilha
            </Button>
          )}
          {/* Sem número no ERP o pedido produz, mas não fatura por aqui. A
              busca vai em bloco pelo numeroLoja, não pedido a pedido. */}
          <Button
            variant="outline"
            size="sm"
            disabled={trabalhando !== null}
            onClick={() => acao('resolver-erp')}
            className="gap-2"
          >
            {trabalhando === 'resolver-erp'
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Receipt className="h-4 w-4" />}
            Buscar número no ERP
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
