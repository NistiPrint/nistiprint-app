import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import ProductService from '@/services/ProductService';
import { AlertTriangle, Check, Plus, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

// Revisão dos eixos de variação.
//
// O que está nesta fila e por quê: o backfill leu do SKU apenas o MIOLO — o
// primeiro segmento, que corresponde a um produto `MIOLO-*` cadastrado e é
// portanto conferível. Estampa e acabamento ficaram de fora de propósito.
// A gramática `MIOLO_ESTAMPA_ACABAMENTO` só vale para 27 dos 44 acabados: 14
// usam espaço em vez de `_` e 3 têm só dois segmentos. Deduzir ali seria gravar
// erro no banco com cara de dado.
//
// Por isso esta tela não sugere nada. Ela mostra o que já está gravado, o que
// falta, e deixa a decisão com quem conhece o produto.

function OpcaoNova({ eixo, onCriada }) {
  const [aberto, setAberto] = useState(false);
  const [codigo, setCodigo] = useState('');
  const [nome, setNome] = useState('');
  const [salvando, setSalvando] = useState(false);

  const criar = async () => {
    if (!codigo.trim()) return;
    setSalvando(true);
    try {
      const opcao = await ProductService.createAxisOption(eixo.codigo, codigo.trim(), nome.trim() || codigo.trim());
      toast.success(`Opção ${opcao.codigo} cadastrada em ${eixo.nome}.`);
      setCodigo(''); setNome(''); setAberto(false);
      onCriada();
    } catch (erro) {
      toast.error(erro.response?.data?.error || erro.message);
    } finally {
      setSalvando(false);
    }
  };

  if (!aberto) {
    return (
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => setAberto(true)}>
        <Plus className="mr-1 h-3 w-3" /> nova {eixo.nome.toLowerCase()}
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 p-2">
      <Input className="h-8 w-32" placeholder="código" value={codigo}
             onChange={(e) => setCodigo(e.target.value)} />
      <Input className="h-8 w-56" placeholder="nome (opcional)" value={nome}
             onChange={(e) => setNome(e.target.value)} />
      <Button size="sm" className="h-8" onClick={criar} disabled={salvando || !codigo.trim()}>Criar</Button>
      <Button size="sm" variant="ghost" className="h-8" onClick={() => setAberto(false)}>Cancelar</Button>
    </div>
  );
}

function LinhaPendente({ item, eixos, onSalvo }) {
  const jaGravados = useMemo(() => {
    const mapa = {};
    for (const valor of item.valores_atuais || []) {
      const eixo = eixos.find((e) => e.id === valor.eixo_id);
      if (!eixo) continue;
      const opcao = (eixo.produto_eixo_opcoes || []).find((o) => o.id === valor.opcao_id);
      if (opcao) mapa[eixo.codigo] = opcao.codigo;
    }
    return mapa;
  }, [item, eixos]);

  const [escolhas, setEscolhas] = useState(jaGravados);
  const [salvando, setSalvando] = useState(false);
  useEffect(() => { setEscolhas(jaGravados); }, [jaGravados]);

  const completo = eixos.every((eixo) => escolhas[eixo.codigo]);

  const salvar = async () => {
    setSalvando(true);
    try {
      await ProductService.setVariationValues(item.produto_id, escolhas);
      toast.success(`${item.sku}: eixos gravados.`);
      onSalvo();
    } catch (erro) {
      toast.error(erro.response?.data?.error || erro.message);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="rounded-lg border p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <Link to={`/produtos/${item.produto_id}/editar`} className="font-medium hover:underline">
            {item.nome || item.sku}
          </Link>
          <p className="font-mono text-xs text-muted-foreground">{item.sku}</p>
        </div>
        {item.sku_observado && item.sku_observado !== item.sku && (
          <Badge variant="outline" className="text-[10px]">SKU no backfill: {item.sku_observado}</Badge>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {eixos.map((eixo) => {
          const opcoes = (eixo.produto_eixo_opcoes || []).filter((o) => o.ativo !== false);
          const gravado = Boolean(jaGravados[eixo.codigo]);
          return (
            <div key={eixo.id} className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-medium">
                {eixo.nome}
                {gravado && (
                  <Badge variant="outline" className="border-emerald-400 text-[9px] text-emerald-700">
                    do backfill
                  </Badge>
                )}
              </div>
              <Select
                value={escolhas[eixo.codigo] || ''}
                onValueChange={(valor) => setEscolhas((atual) => ({ ...atual, [eixo.codigo]: valor }))}
              >
                <SelectTrigger className="h-9">
                  <SelectValue placeholder={`Escolher ${eixo.nome.toLowerCase()}`} />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {opcoes.map((opcao) => (
                    <SelectItem key={opcao.id} value={opcao.codigo}>
                      {opcao.codigo}{opcao.nome && opcao.nome !== opcao.codigo ? ` — ${opcao.nome}` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {eixos.map((eixo) => <OpcaoNova key={eixo.id} eixo={eixo} onCriada={onSalvo} />)}
        <Button size="sm" className="ml-auto" onClick={salvar} disabled={!completo || salvando}>
          <Check className="mr-2 h-4 w-4" /> Gravar eixos
        </Button>
      </div>
      {!completo && (
        <p className="mt-2 text-xs text-muted-foreground">
          Todos os eixos precisam de valor — a combinação é o que identifica a variação.
        </p>
      )}
    </div>
  );
}

export default function ProdutoEixosPage() {
  const [pendentes, setPendentes] = useState([]);
  const [eixos, setEixos] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [filtro, setFiltro] = useState('');

  const carregar = async () => {
    setCarregando(true);
    try {
      const dados = await ProductService.getVariationReviewQueue();
      setPendentes(dados.pendentes || []);
      setEixos(dados.eixos || []);
    } catch (erro) {
      toast.error(`Não foi possível carregar a fila: ${erro.response?.data?.error || erro.message}`);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => { carregar(); }, []);

  const visiveis = useMemo(() => {
    const termo = filtro.trim().toLowerCase();
    if (!termo) return pendentes;
    return pendentes.filter((item) =>
      `${item.sku || ''} ${item.nome || ''}`.toLowerCase().includes(termo));
  }, [pendentes, filtro]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Eixos das variações</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            O miolo foi lido do SKU porque corresponde a um produto cadastrado e dá para
            conferir. Estampa e acabamento não: a gramática de três segmentos só vale para
            27 dos 44 acabados. Estes ficaram para você.
          </p>
        </div>
        <Button variant="outline" onClick={carregar} disabled={carregando}>
          <RefreshCw className={`mr-2 h-4 w-4 ${carregando ? 'animate-spin' : ''}`} /> Atualizar
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {pendentes.length} {pendentes.length === 1 ? 'produto pendente' : 'produtos pendentes'}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="Filtrar por SKU ou nome" value={filtro}
                 onChange={(e) => setFiltro(e.target.value)} className="max-w-sm" />

          {carregando && <div className="h-24 animate-pulse rounded-md bg-muted" />}

          {!carregando && pendentes.length === 0 && (
            <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
              <Check className="h-4 w-4" /> Nenhum produto na fila de revisão.
            </div>
          )}

          {!carregando && eixos.length === 0 && pendentes.length > 0 && (
            <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              <AlertTriangle className="h-4 w-4" />
              Não há eixos cadastrados — sem eles não é possível gravar variação.
            </div>
          )}

          {visiveis.map((item) => (
            <LinhaPendente key={item.produto_id} item={item} eixos={eixos} onSalvo={carregar} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
