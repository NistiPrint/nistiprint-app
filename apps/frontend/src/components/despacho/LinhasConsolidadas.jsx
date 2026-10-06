import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AlertTriangle, GripVertical, MoreHorizontal, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { memo, useCallback, useMemo, useRef, useState } from 'react';
import { inserirLinha, linhaVazia, moverLinha, normalizarLinha, totalizarLinhas } from '@/lib/consolidacaoEditavel';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';

const COLUNAS_COMPACTAS = [
  ['sku_externo', 'SKU'],
  ['variacao', 'Variação'],
  ['miolo_nome', 'Miolo'],
];

function larguraPorConteudo(linhas, campo, titulo) {
  const maior = linhas.reduce((maximo, linha) => Math.max(maximo, String(linha[campo] || '').length), titulo.length);
  return `${Math.max(12, Math.ceil(maior * 1.15) + 3)}ch`;
}

function statusBadge(status) {
  if (status === 'resolvido') return <span className="ml-1 text-emerald-600" title="Vínculo resolvido">✓</span>;
  if (status === 'ambiguo') return <span className="ml-1 text-amber-600" title="Mais de um vínculo possível">!</span>;
  if (status === 'nao_resolvido') return <span className="ml-1 text-amber-600" title="Sem vínculo de estoque">!</span>;
  return null;
}

const LinhaConsolidada = memo(function LinhaConsolidada({ linha, indice, onEditar, onInserir, onExcluir, onMover, onArrastar }) {
  return (<tr key={linha.client_id} className={`border-t ${linhaVazia(linha) ? 'bg-amber-50/40' : ''}`} draggable onDragStart={() => onArrastar(indice)} onDragOver={(evento) => evento.preventDefault()} onDrop={() => onMover(indice)} onDragEnd={() => onArrastar(null)}>
            <td className="px-2 py-2 text-muted-foreground"><button type="button" className="cursor-grab p-1" title="Arrastar linha" aria-label={`Arrastar linha ${indice + 1}`}><GripVertical className="h-4 w-4" /></button></td>
            {[['descricao', 'Produto'], ...COLUNAS_COMPACTAS].map(([campo, placeholder]) => <td key={campo} className="px-2 py-1.5"><div className="flex min-w-0 items-center"><Input value={linha[campo]} placeholder={placeholder} onChange={(evento) => onEditar(indice, campo, evento.target.value)} className="h-8 min-w-0" title={linha[campo]} />{campo === 'sku_externo' && statusBadge(linha.sku_status)}{campo === 'miolo_nome' && statusBadge(linha.miolo_status)}</div></td>)}
            <td className="px-2 py-1.5"><Input type="number" min="1" step="1" value={linha.quantidade} onChange={(evento) => onEditar(indice, 'quantidade', evento.target.value === '' ? '' : Number(evento.target.value))} className="h-8 text-right" aria-label={`Quantidade da linha ${indice + 1}`} /></td>
            <td className="px-2 py-1.5 text-right"><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Ações da linha ${indice + 1}`}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => onInserir(indice, true)}><Plus className="mr-2 h-4 w-4" /> Inserir acima</DropdownMenuItem><DropdownMenuItem onClick={() => onInserir(indice, false)}><Plus className="mr-2 h-4 w-4" /> Inserir abaixo</DropdownMenuItem><DropdownMenuItem className="text-destructive" onClick={() => onExcluir(indice)}><Trash2 className="mr-2 h-4 w-4" /> Excluir linha</DropdownMenuItem></DropdownMenuContent></DropdownMenu></td>
          </tr>);
});

export default function LinhasConsolidadas({ itens = [], resumo = null, titulo = 'Consolidação do lote', ajuda = null, rotuloDemanda = null, carregando = false, erro = null, className = 'mb-6', onChange, onReset }) {
  const [linhas, setLinhas] = useState(() => itens.map(normalizarLinha));
  const arrastando = useRef(null);
  const linhasRef = useRef(linhas);

  const atualizar = useCallback((proxima) => { linhasRef.current = proxima; setLinhas(proxima); onChange?.(proxima); }, [onChange]);
  const editar = useCallback((indice, campo, valor) => atualizar(linhasRef.current.map((linha, i) => i === indice ? { ...linha, [campo]: valor, manual: true } : linha)), [atualizar]);
  const inserir = useCallback((indice, acima) => atualizar(inserirLinha(linhasRef.current, indice, acima)), [atualizar]);
  const excluir = useCallback((indice) => atualizar(linhasRef.current.filter((_, i) => i !== indice)), [atualizar]);
  const arrastar = useCallback((indice) => { arrastando.current = indice; }, []);
  const mover = useCallback((indice) => {
    if (arrastando.current !== null) atualizar(moverLinha(linhasRef.current, arrastando.current, indice));
    arrastando.current = null;
  }, [atualizar]);
  const restaurar = () => { const proxima = itens.map(normalizarLinha); linhasRef.current = proxima; setLinhas(proxima); onReset?.(proxima); onChange?.(proxima); };

  const totalPecas = useMemo(() => totalizarLinhas(linhas), [linhas]);
  const semVinculo = useMemo(() => linhas.filter((linha) => linha.sku_status === 'nao_resolvido' || linha.sku_status === 'ambiguo' || linha.contabiliza_estoque === false).length, [linhas]);
  const largurasCompactas = useMemo(() => Object.fromEntries(COLUNAS_COMPACTAS.map(([campo, titulo]) => [campo, larguraPorConteudo(linhas, campo, titulo)])), [linhas]);

  if (erro) return <Card className={`border-destructive/50 ${className}`}><CardContent className="py-4 text-sm text-destructive">{erro}</CardContent></Card>;
  if (carregando) return <div className={`h-48 w-full animate-pulse rounded-md bg-muted ${className}`} />;

  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div><div className="text-sm font-medium">{titulo}</div>{ajuda && <div className="text-xs text-muted-foreground">{ajuda}</div>}</div>
        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          {rotuloDemanda && <span>{rotuloDemanda} ·</span>}<span>{linhas.length} linhas</span><span>·</span><span className="font-medium text-foreground">{Math.round(totalPecas)} itens</span>
          {resumo?.total_miolos > 0 && <span>· {resumo.total_miolos} miolos</span>}
          <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 text-xs" onClick={restaurar} disabled={!linhas.some((linha) => linha.manual)}><RotateCcw className="h-3 w-3" /> Restaurar</Button>
        </div>
      </div>
      {semVinculo > 0 && <div className="mb-2 flex items-center gap-1.5 text-xs text-amber-700"><AlertTriangle className="h-3 w-3 shrink-0" />{semVinculo} linha{semVinculo === 1 ? '' : 's'} sem vínculo de estoque. A publicação continuará, mas não haverá baixa para essas linhas.</div>}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full table-fixed text-sm" style={{ minWidth: `calc(600px + ${largurasCompactas.sku_externo} + ${largurasCompactas.variacao} + ${largurasCompactas.miolo_nome})` }}><colgroup><col className="w-10" /><col /><col style={{ width: largurasCompactas.sku_externo }} /><col style={{ width: largurasCompactas.variacao }} /><col style={{ width: largurasCompactas.miolo_nome }} /><col className="w-28" /><col className="w-12" /></colgroup><thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th className="px-2 py-2" aria-label="Mover" /><th className="px-3 py-2 font-medium">Produto</th><th className="px-3 py-2 font-medium">SKU</th><th className="px-3 py-2 font-medium">Variação</th><th className="px-3 py-2 font-medium">Miolo</th><th className="px-3 py-2 text-right font-medium">Quantidade</th><th className="px-2 py-2" aria-label="Ações" /></tr></thead>
          <tbody>{linhas.map((linha, indice) => <LinhaConsolidada key={linha.client_id} linha={linha} indice={indice}
            onEditar={editar} onInserir={inserir} onExcluir={excluir} onMover={mover} onArrastar={arrastar} />)}</tbody>
        </table>
      </div>
      <Button type="button" variant="outline" size="sm" className="mt-2 gap-1.5" onClick={() => atualizar(inserirLinha(linhas, linhas.length, false))}><Plus className="h-4 w-4" /> Adicionar linha</Button>
    </div>
  );
}
