import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import ProductSearchInput from '@/components/produtos/ProductSearchInput';
import ProductService from '@/services/ProductService';
import { AlertTriangle, Check, Package, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

// Fila de cadastro dos códigos que aparecem em pedido e não chegam a produto.
//
// Duas situações muito diferentes, separadas de propósito:
//
//   chega_ao_miolo = false  A linha entra na produção SEM miolo. É a fila
//                           urgente, e é onde moram os combos.
//   chega_ao_miolo = true   A fábrica sabe o que imprimir (o miolo sai da
//                           heurística de prefixo), mas o item não conta
//                           estoque e a variação continua sendo texto.
//
// Cadastrar um combo aqui faz a consolidação passar a explodi-lo sozinha em
// seus produtos acabados (migration 20260901140000) — não é preciso mexer em
// nenhuma demanda depois.

const inteiro = (v) => Math.round(Number(v || 0));

function FormularioKit({ codigo, titulo, onPronto, onCancelar }) {
  const [sku, setSku] = useState('');
  const [nome, setNome] = useState(titulo || '');
  const [componentes, setComponentes] = useState([]);
  const [busca, setBusca] = useState('');
  const [salvando, setSalvando] = useState(false);

  const adicionar = (produto) => {
    if (!produto?.id) return;
    setBusca('');
    if (componentes.some((c) => String(c.id) === String(produto.id))) return;
    setComponentes((atual) => [...atual, { id: produto.id, sku: produto.sku, nome: produto.name || produto.nome, quantidade: 1 }]);
  };

  const salvar = async () => {
    if (!sku.trim()) return toast.error('O SKU é obrigatório e é você quem escreve.');
    if (componentes.length < 1) return toast.error('Um kit precisa de pelo menos um produto acabado.');
    setSalvando(true);
    try {
      // 1. o produto kit
      const criado = await ProductService.create({
        sku: sku.trim(),
        name: nome.trim() || sku.trim(),
        formato: 'kit',
        material_type: 'produto_acabado',
        status: 'inativo',
        estagio: 'RASCUNHO',
      });
      const kitId = criado.produto_id || criado.id;

      // 2. a ficha: produtos acabados. O trigger do banco recusa qualquer outro
      //    tipo aqui, e recusa kit dentro de kit.
      for (const componente of componentes) {
        await ProductService.addBOMComponent(kitId, componente.id, Number(componente.quantidade) || 1);
      }

      // 3. o apelido: é por ele que o código do pedido chega ao kit.
      await ProductService.addAlias({ produto_id: kitId, codigo_externo: codigo, tipo: 'SKU' });

      toast.success(`${codigo} cadastrado como kit. A consolidação passa a explodi-lo sozinha.`);
      onPronto();
    } catch (erro) {
      toast.error(erro.response?.data?.error || erro.message);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="mt-3 space-y-3 rounded-md border bg-muted/30 p-4">
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium">SKU interno do kit</label>
          <Input value={sku} onChange={(e) => setSku(e.target.value)} placeholder="digite o SKU" />
          <p className="mt-1 text-xs text-muted-foreground">
            O sistema não sugere SKU. O código do anúncio ({codigo}) fica como apelido.
          </p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">Nome</label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="nome do kit" />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium">Produtos que compõem o kit</label>
        <ProductSearchInput
          value={busca}
          onChange={setBusca}
          onProductSelect={adicionar}
          placeholder="Buscar produto acabado..."
        />
        <div className="mt-2 space-y-2">
          {componentes.length === 0 && (
            <p className="text-xs text-muted-foreground">Nenhum produto ainda.</p>
          )}
          {componentes.map((componente, indice) => (
            <div key={componente.id} className="flex items-center gap-2 rounded border bg-background px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{componente.nome}</p>
                <p className="font-mono text-xs text-muted-foreground">{componente.sku}</p>
              </div>
              <Input
                type="number" min="1" className="h-8 w-20 text-right"
                value={componente.quantidade}
                onChange={(e) => setComponentes((atual) => atual.map((item, i) =>
                  i === indice ? { ...item, quantidade: Math.max(1, Number(e.target.value) || 1) } : item))}
              />
              <Button variant="ghost" size="icon" className="h-8 w-8"
                      onClick={() => setComponentes((atual) => atual.filter((_, i) => i !== indice))}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancelar}>Cancelar</Button>
        <Button onClick={salvar} disabled={salvando}>
          <Check className="mr-2 h-4 w-4" /> Cadastrar kit
        </Button>
      </div>
    </div>
  );
}

function Fila({ titulo, ajuda, itens, destaque, onCadastrado }) {
  const [abertoEm, setAbertoEm] = useState(null);
  if (!itens.length) return null;
  const total = itens.reduce((soma, item) => soma + Number(item.itens || 0), 0);

  return (
    <Card className={destaque ? 'border-amber-300' : undefined}>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-baseline gap-2 text-base">
          {destaque && <AlertTriangle className="h-4 w-4 text-amber-500" />}
          {titulo}
          <span className="text-xs font-normal text-muted-foreground">
            {itens.length} códigos · {inteiro(total)} itens de pedido
          </span>
        </CardTitle>
        <p className="text-sm text-muted-foreground">{ajuda}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {itens.map((item) => (
          <div key={item.codigo} className="rounded-lg border p-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{item.codigo}</span>
                  {item.parece_combo && (
                    <Badge variant="outline" className="border-sky-400 text-[9px] text-sky-700">combo</Badge>
                  )}
                  {item.miolo_chave && (
                    <Badge variant="secondary" className="text-[9px]">miolo {item.miolo_chave}</Badge>
                  )}
                </div>
                <p className="truncate text-xs text-muted-foreground">{item.titulo_exemplo || '—'}</p>
              </div>
              <div className="text-right text-xs tabular-nums text-muted-foreground">
                <div>{inteiro(item.itens)} itens</div>
                <div>{inteiro(item.unidades)} unid.</div>
              </div>
              <Button size="sm" variant={abertoEm === item.codigo ? 'secondary' : 'outline'}
                      onClick={() => setAbertoEm(abertoEm === item.codigo ? null : item.codigo)}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Cadastrar como kit
              </Button>
            </div>
            {abertoEm === item.codigo && (
              <FormularioKit
                codigo={item.codigo}
                titulo={item.titulo_exemplo}
                onCancelar={() => setAbertoEm(null)}
                onPronto={() => { setAbertoEm(null); onCadastrado(); }}
              />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export default function ProdutoKitsPage() {
  const [pendentes, setPendentes] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [soCombos, setSoCombos] = useState(false);

  const carregar = async () => {
    setCarregando(true);
    try {
      setPendentes(await ProductService.getPendingCodes());
    } catch (erro) {
      toast.error(`Não foi possível carregar a fila: ${erro.response?.data?.error || erro.message}`);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => { carregar(); }, []);

  const { semMiolo, comMiolo } = useMemo(() => {
    const base = soCombos ? pendentes.filter((item) => item.parece_combo) : pendentes;
    return {
      semMiolo: base.filter((item) => !item.chega_ao_miolo),
      comMiolo: base.filter((item) => item.chega_ao_miolo),
    };
  }, [pendentes, soCombos]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Kits e códigos sem produto</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Códigos que aparecem em pedido e não chegam a nenhum produto interno. Cadastrar
            um combo aqui faz a consolidação passar a explodi-lo sozinha nos produtos que o
            compõem — nenhuma demanda precisa ser ajustada depois.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant={soCombos ? 'secondary' : 'outline'} onClick={() => setSoCombos((v) => !v)}>
            <Package className="mr-2 h-4 w-4" /> {soCombos ? 'Mostrando combos' : 'Só combos'}
          </Button>
          <Button variant="outline" onClick={carregar} disabled={carregando}>
            <RefreshCw className={`mr-2 h-4 w-4 ${carregando ? 'animate-spin' : ''}`} /> Atualizar
          </Button>
        </div>
      </div>

      {carregando && <div className="h-40 animate-pulse rounded-md bg-muted" />}

      {!carregando && pendentes.length === 0 && (
        <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
          <Check className="h-4 w-4" /> Todo código de pedido chega a um produto interno.
        </div>
      )}

      {!carregando && (
        <>
          <Fila
            destaque
            titulo="Não chegam a nada"
            ajuda="A linha entra na produção sem miolo. É aqui que estão os combos, e é a fila que precisa de cadastro primeiro."
            itens={semMiolo}
            onCadastrado={carregar}
          />
          <Fila
            titulo="Chegam ao miolo, mas não ao produto"
            ajuda="A fábrica sabe o que imprimir — o miolo sai da heurística de prefixo. Falta o cadastro para o item movimentar estoque e para a variação deixar de ser texto."
            itens={comMiolo}
            onCadastrado={carregar}
          />
        </>
      )}
    </div>
  );
}
