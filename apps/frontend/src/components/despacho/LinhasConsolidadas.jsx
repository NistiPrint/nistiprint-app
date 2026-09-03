import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { AlertTriangle, GripVertical, MoreHorizontal, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { inserirLinha, linhaVazia, moverLinha, normalizarLinha, totalizarLinhas } from '@/lib/consolidacaoEditavel';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';

function statusBadge(status) {
  if (status === 'resolvido') return <span className="ml-1 text-emerald-600" title="Vínculo resolvido">✓</span>;
  if (status === 'ambiguo') return <span className="ml-1 text-amber-600" title="Mais de um vínculo possível">!</span>;
  if (status === 'nao_resolvido') return <span className="ml-1 text-amber-600" title="Sem vínculo de estoque">!</span>;
  return null;
}

export default function LinhasConsolidadas({ itens = [], resumo = null, titulo = 'Consolidação do lote', ajuda = null, rotuloDemanda = null, carregando = false, erro = null, className = 'mb-6', onChange, onReset }) {
  const [linhas, setLinhas] = useState(() => itens.map(normalizarLinha));
  const [arrastando, setArrastando] = useState(null);

  const atualizar = (proxima) => { setLinhas(proxima); onChange?.(proxima); };
  const editar = (indice, campo, valor) => atualizar(linhas.map((linha, i) => i === indice ? { ...linha, [campo]: valor, manual: true } : linha));
  const restaurar = () => { const proxima = itens.map(normalizarLinha); setLinhas(proxima); onReset?.(proxima); onChange?.(proxima); };

  if (erro) return <Card className={`border-destructive/50 ${className}`}><CardContent className="py-4 text-sm text-destructive">{erro}</CardContent></Card>;
  if (carregando) return <div className={`h-48 w-full animate-pulse rounded-md bg-muted ${className}`} />;

  const totalPecas = totalizarLinhas(linhas);
  const semVinculo = linhas.filter((linha) => linha.sku_status === 'nao_resolvido' || linha.sku_status === 'ambiguo' || linha.contabiliza_estoque === false).length;
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
        <table className="w-full min-w-[760px] text-sm"><thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th className="w-8 px-2 py-2" aria-label="Mover" /><th className="px-3 py-2 font-medium">Produto</th><th className="px-3 py-2 font-medium">SKU</th><th className="px-3 py-2 font-medium">Variação</th><th className="px-3 py-2 font-medium">Miolo</th><th className="w-28 px-3 py-2 text-right font-medium">Quantidade</th><th className="w-12 px-2 py-2" aria-label="Ações" /></tr></thead>
          <tbody>{linhas.map((linha, indice) => <tr key={linha.client_id} className={`border-t ${linhaVazia(linha) ? 'bg-amber-50/40' : ''}`} draggable onDragStart={() => setArrastando(indice)} onDragOver={(evento) => evento.preventDefault()} onDrop={() => { if (arrastando !== null) atualizar(moverLinha(linhas, arrastando, indice)); setArrastando(null); }} onDragEnd={() => setArrastando(null)}>
            <td className="px-2 py-2 text-muted-foreground"><button type="button" className="cursor-grab p-1" title="Arrastar linha" aria-label={`Arrastar linha ${indice + 1}`}><GripVertical className="h-4 w-4" /></button></td>
            {[['descricao', 'Produto'], ['sku_externo', 'SKU'], ['variacao', 'Variação'], ['miolo_nome', 'Miolo']].map(([campo, placeholder]) => <td key={campo} className="px-2 py-1.5"><div className="flex items-center"><Input value={linha[campo]} placeholder={placeholder} onChange={(evento) => editar(indice, campo, evento.target.value)} className="h-8 min-w-[130px]" />{campo === 'sku_externo' && statusBadge(linha.sku_status)}{campo === 'miolo_nome' && statusBadge(linha.miolo_status)}</div></td>)}
            <td className="px-2 py-1.5"><Input type="number" min="1" step="1" value={linha.quantidade} onChange={(evento) => editar(indice, 'quantidade', evento.target.value === '' ? '' : Number(evento.target.value))} className="h-8 text-right" aria-label={`Quantidade da linha ${indice + 1}`} /></td>
            <td className="px-2 py-1.5 text-right"><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Ações da linha ${indice + 1}`}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onClick={() => atualizar(inserirLinha(linhas, indice, true))}><Plus className="mr-2 h-4 w-4" /> Inserir acima</DropdownMenuItem><DropdownMenuItem onClick={() => atualizar(inserirLinha(linhas, indice, false))}><Plus className="mr-2 h-4 w-4" /> Inserir abaixo</DropdownMenuItem><DropdownMenuItem className="text-destructive" onClick={() => atualizar(linhas.filter((_, i) => i !== indice))}><Trash2 className="mr-2 h-4 w-4" /> Excluir linha</DropdownMenuItem></DropdownMenuContent></DropdownMenu></td>
          </tr>)}</tbody>
        </table>
      </div>
      <Button type="button" variant="outline" size="sm" className="mt-2 gap-1.5" onClick={() => atualizar(inserirLinha(linhas, linhas.length, false))}><Plus className="h-4 w-4" /> Adicionar linha</Button>
    </div>
  );
}
