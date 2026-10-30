import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import PageHeader from '@/components/ui/PageHeader';
import ProductService from '../../services/ProductService';
import CategoryService from '../../services/CategoryService';
import { aplicarEdicoes, interpretarColagem, normalizarQuantidade } from '../../lib/composicaoLote';

export default function ComposicaoLotePage() {
  const [lado, setLado] = useState('destinatarios');
  const [filtro, setFiltro] = useState('');
  const [candidatos, setCandidatos] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [categoria, setCategoria] = useState('');
  const [tipos, setTipos] = useState({ destinatarios: '', componentes: '' });
  const [selecionados, setSelecionados] = useState({ destinatarios: [], componentes: [] });
  const [celulasSelecionadas, setCelulasSelecionadas] = useState([]);
  const [ancoraSelecao, setAncoraSelecao] = useState(null);
  const [quantidadeEmLote, setQuantidadeEmLote] = useState('');
  const [snapshot, setSnapshot] = useState(null);
  const [edicoes, setEdicoes] = useState({});
  const [desfazer, setDesfazer] = useState([]);
  const [refazer, setRefazer] = useState([]);
  const [previa, setPrevia] = useState(null);
  const [chaveIdempotencia, setChaveIdempotencia] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const rows = useMemo(() => snapshot?.produtos?.filter(p => selecionados.destinatarios.includes(Number(p.id))) || [], [snapshot, selecionados]);
  const columns = useMemo(() => {
    const byId = new Map((snapshot?.produtos || []).map(p => [Number(p.id), p]));
    for (const p of snapshot?.componentes || []) byId.set(Number(p.id), p);
    return selecionados.componentes.map(id => byId.get(id)).filter(Boolean);
  }, [snapshot, selecionados]);
  const resumo = useMemo(() => Object.values(edicoes).reduce((totals, op) => {
    if (op.acao === 'remover') totals.remocoes += 1;
    else if (snapshot?.composicoes?.[String(op.produto_id)]?.some(line => Number(line.componente_id) === Number(op.componente_id))) totals.alteracoes += 1;
    else totals.inclusoes += 1;
    return totals;
  }, { inclusoes: 0, alteracoes: 0, remocoes: 0 }), [edicoes, snapshot]);
  const tipo = tipos[lado];

  useEffect(() => { CategoryService.getAll().then(setCategorias).catch(() => setCategorias([])); }, []);

  const carregarCandidatos = useCallback(async () => {
    setCarregando(true);
    try {
      const data = await ProductService.getBOMBatchCandidates({ q: filtro, tipo_material: tipo, category_id: categoria || undefined, per_page: 100 });
      setCandidatos(data.produtos || []);
    } catch (error) { toast.error(error.response?.data?.error || 'Falha ao buscar produtos.'); }
    finally { setCarregando(false); }
  }, [categoria, filtro, tipo]);
  useEffect(() => { carregarCandidatos(); }, [carregarCandidatos]);

  const alternar = (id) => setSelecionados(previous => ({ ...previous, [lado]: previous[lado].includes(id) ? previous[lado].filter(value => value !== id) : [...previous[lado], id] }));
  const abrirMatriz = async () => {
    if (!selecionados.destinatarios.length || !selecionados.componentes.length) return toast.error('Selecione produtos nos dois eixos.');
    if (selecionados.destinatarios.length * selecionados.componentes.length > 5000) return toast.error('A matriz pode ter no máximo 5.000 células. Reduza uma das seleções.');
    setCarregando(true);
    try {
      const data = await ProductService.getBOMBatchSnapshot(selecionados.destinatarios, selecionados.componentes);
      setSnapshot(data); setEdicoes({}); setDesfazer([]); setRefazer([]); setPrevia(null); setChaveIdempotencia(null); setCelulasSelecionadas([]); setAncoraSelecao(null);
    } catch (error) { toast.error(error.response?.data?.error || 'Falha ao carregar composições.'); }
    finally { setCarregando(false); }
  };
  const alterarCelula = (rowId, columnId, value) => {
    const key = `${rowId}:${columnId}`;
    setDesfazer(history => [...history.slice(-49), edicoes]); setRefazer([]); setPrevia(null); setChaveIdempotencia(null);
    if (value === '') { setEdicoes({ ...edicoes, [key]: { produto_id: rowId, componente_id: columnId, acao: 'remover' } }); return; }
    setEdicoes({ ...edicoes, [key]: { produto_id: rowId, componente_id: columnId, acao: 'definir', quantidade: value } });
  };
  const valorCelula = (rowId, columnId) => {
    const edit = edicoes[`${rowId}:${columnId}`];
    if (edit?.acao === 'remover') return '';
    if (edit?.acao === 'definir') return edit.quantidade;
    return snapshot?.composicoes?.[String(rowId)]?.find(line => Number(line.componente_id) === columnId)?.quantidade_necessaria ?? '';
  };
  const selecionarCelula = (rowIndex, columnIndex, event) => {
    const cell = { row: rowIndex, column: columnIndex };
    if (event.shiftKey && ancoraSelecao) {
      const rowStart = Math.min(ancoraSelecao.row, rowIndex);
      const rowEnd = Math.max(ancoraSelecao.row, rowIndex);
      const columnStart = Math.min(ancoraSelecao.column, columnIndex);
      const columnEnd = Math.max(ancoraSelecao.column, columnIndex);
      const rectangle = [];
      for (let row = rowStart; row <= rowEnd; row += 1) {
        for (let column = columnStart; column <= columnEnd; column += 1) rectangle.push({ row, column });
      }
      setCelulasSelecionadas(rectangle);
    } else if (event.ctrlKey || event.metaKey) {
      setCelulasSelecionadas(current => current.some(item => item.row === rowIndex && item.column === columnIndex)
        ? current.filter(item => item.row !== rowIndex || item.column !== columnIndex)
        : [...current, cell]);
      setAncoraSelecao(cell);
    } else {
      setAncoraSelecao(cell);
      setCelulasSelecionadas([cell]);
    }
  };
  const preencherCelulasSelecionadas = () => {
    if (!celulasSelecionadas.length) return;
    try {
      const quantidade = normalizarQuantidade(quantidadeEmLote);
      const changes = celulasSelecionadas.map(cell => ({
        produtoId: Number(rows[cell.row].id), componenteId: Number(columns[cell.column].id),
        acao: 'definir', quantidade,
      }));
      setDesfazer(history => [...history.slice(-49), edicoes]); setRefazer([]);
      setEdicoes(aplicarEdicoes(edicoes, changes)); setPrevia(null); setChaveIdempotencia(null);
    } catch (error) { toast.error(error.message); }
  };
  const copiarLinha = async (rowId) => {
    try {
      await navigator.clipboard.writeText(columns.map(column => valorCelula(Number(rowId), Number(column.id))).join('\t'));
      toast.success('Linha copiada. Selecione outra célula e cole com Ctrl+V.');
    } catch { toast.error('Não foi possível copiar a linha neste navegador.'); }
  };
  const revisar = async () => {
    try {
      const result = await ProductService.previewBOMBatch(selecionados.destinatarios, Object.values(edicoes), snapshot.tokens);
      setPrevia(result); setChaveIdempotencia(crypto.randomUUID());
    } catch (error) { toast.error(error.response?.data?.error || 'Não foi possível gerar a revisão.'); }
  };
  const salvar = async () => {
    if (!previa) return;
    try {
      const response = await ProductService.applyBOMBatch({ produto_ids: selecionados.destinatarios, operacoes: Object.values(edicoes), tokens: snapshot.tokens, revisao: previa.revisao, idempotency_key: chaveIdempotencia, composicoes_anteriores: previa.composicoes_anteriores, produtos_esperados: previa.produtos });
      toast.success(response.resultado?.custos_status === 'concluido' ? 'Composição salva e custos atualizados.' : 'Composição salva; custos em atualização.'); setEdicoes({}); setPrevia(null); setChaveIdempotencia(null); await abrirMatriz();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Falha ao salvar o lote.');
      if (error.response?.status === 409) {
        setPrevia(null); setChaveIdempotencia(null);
        try {
          const latest = await ProductService.getBOMBatchSnapshot(selecionados.destinatarios, selecionados.componentes);
          setSnapshot(latest);
        } catch (refreshError) {
          toast.error(refreshError.response?.data?.error || 'Não foi possível atualizar a matriz após o conflito.');
        }
      }
    }
  };
  const colar = (event, rowIndex, columnIndex) => {
    const text = event.clipboardData.getData('text');
    if (!text.includes('\t') && !text.includes('\n')) return;
    event.preventDefault();
    try {
      const changes = interpretarColagem(text, rowIndex, columnIndex, rows.length, columns.length).map(cell => ({ produtoId: Number(rows[cell.row].id), componenteId: Number(columns[cell.column].id), acao: 'definir', quantidade: cell.quantidade }));
      setPrevia(null); setChaveIdempotencia(null); setDesfazer(history => [...history.slice(-49), edicoes]); setRefazer([]); setEdicoes(aplicarEdicoes(edicoes, changes));
    } catch (error) { toast.error(error.message); }
  };

  return <div className="space-y-5 p-6">
    <PageHeader title="Composição em lote" description="Edite várias fichas técnicas em uma matriz e revise antes de salvar." />
    <div className="flex flex-wrap items-end gap-3 rounded-lg border p-4">
      <div><label className="mb-1 block text-sm">Eixo de seleção</label><select className="h-10 rounded-md border bg-background px-3" value={lado} onChange={e => setLado(e.target.value)}><option value="destinatarios">Produtos que recebem composição</option><option value="componentes">Componentes</option></select></div>
      <div><label className="mb-1 block text-sm">Buscar por nome ou SKU</label><Input value={filtro} onChange={e => setFiltro(e.target.value)} placeholder="Digite para filtrar" /></div>
      <div><label className="mb-1 block text-sm">Tipo de material</label><select className="h-10 rounded-md border bg-background px-3" value={tipo} onChange={e => setTipos(current => ({ ...current, [lado]: e.target.value }))}><option value="">Todos</option><option value="materia_prima">Matéria-prima</option><option value="intermediario">Intermediário</option><option value="produto_acabado">Acabado</option></select></div>
      <div><label className="mb-1 block text-sm">Categoria</label><select className="h-10 rounded-md border bg-background px-3" value={categoria} onChange={e => setCategoria(e.target.value)}><option value="">Todas</option>{categorias.map(cat => <option key={cat.id} value={cat.id}>{cat.nome}</option>)}</select></div>
      <Button variant="outline" onClick={() => setLado(lado === 'destinatarios' ? 'componentes' : 'destinatarios')}>Alternar eixo</Button>
      <Button variant="outline" onClick={() => { setLado('destinatarios'); setTipos({ destinatarios: 'intermediario', componentes: 'materia_prima' }); }}>Intermediários × matérias-primas</Button>
      <Button variant="outline" onClick={() => { setLado('destinatarios'); setTipos({ destinatarios: 'produto_acabado', componentes: 'intermediario' }); }}>Acabados × intermediários</Button>
      <Button disabled={carregando} onClick={carregarCandidatos}>Atualizar lista</Button>
      <span className="text-sm text-muted-foreground">{selecionados.destinatarios.length} destinatários · {selecionados.componentes.length} componentes</span>
      <div className="max-h-64 w-full overflow-auto rounded-md border"><table className="w-full text-sm"><tbody>{candidatos.map(p => { const id = Number(p.id); return <tr key={id} className="border-b"><td className="w-10 p-2"><Checkbox checked={selecionados[lado].includes(id)} onCheckedChange={() => alternar(id)} /></td><td className="p-2">{p.sku}</td><td className="p-2">{p.nome || p.name}</td><td className="p-2">{p.tipo_material || p.material_type}</td></tr>; })}</tbody></table></div>
      <Button onClick={abrirMatriz} disabled={carregando || !selecionados.destinatarios.length || !selecionados.componentes.length}>Carregar matriz</Button>
    </div>
    {snapshot && <div className="space-y-3">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Matriz · vazio remove vínculo existente</h2><span className="text-sm text-muted-foreground">{Object.keys(edicoes).length} células alteradas</span></div>
      <div className="flex flex-wrap items-end gap-2 rounded-md border p-3"><div><label className="mb-1 block text-xs">Quantidade para preencher</label><Input className="w-40" value={quantidadeEmLote} onChange={event => setQuantidadeEmLote(event.target.value)} placeholder="Ex.: 0,5" /></div><Button variant="outline" disabled={!celulasSelecionadas.length} onClick={preencherCelulasSelecionadas}>Preencher {celulasSelecionadas.length} células</Button><span className="text-xs text-muted-foreground">Clique para selecionar; Shift+clique seleciona uma faixa; Ctrl/Cmd+clique alterna células.</span></div>
      <div className="max-h-[65vh] overflow-auto rounded-md border"><table className="min-w-full border-collapse text-sm"><thead className="sticky top-0 bg-background"><tr><th className="sticky left-0 z-10 min-w-64 border bg-background p-2 text-left">Produto a compor</th>{columns.map(c => <th key={c.id} className="min-w-36 border p-2">{c.sku}<br />{c.nome || c.name}<br /><span className="font-normal text-muted-foreground">{c.unidade_medida || 'un'}</span></th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={row.id}><th className="sticky left-0 border bg-background p-2 text-left"><div className="flex items-center justify-between gap-2"><span>{row.sku} · {row.nome || row.name}</span><Button type="button" size="sm" variant="ghost" onClick={() => copiarLinha(row.id)}>Copiar linha</Button></div></th>{columns.map((col, columnIndex) => { const original = snapshot.composicoes[String(row.id)]?.find(line => Number(line.componente_id) === Number(col.id)); const cellSelected = celulasSelecionadas.some(cell => cell.row === rowIndex && cell.column === columnIndex); const cellClasses = [original?.is_inherited ? 'bg-amber-50' : '', cellSelected ? 'ring-2 ring-inset ring-primary' : ''].filter(Boolean).join(' '); return <td key={col.id} className="border p-1"><Input aria-label={`${row.sku} / ${col.sku}`} title={original?.is_inherited ? 'Componente herdado: salvar uma mudança personaliza esta composição.' : ''} className={cellClasses} value={valorCelula(Number(row.id), Number(col.id))} onClick={event => selecionarCelula(rowIndex, columnIndex, event)} onChange={e => alterarCelula(Number(row.id), Number(col.id), e.target.value)} onPaste={e => colar(e, rowIndex, columnIndex)} /></td>; })}</tr>)}</tbody></table></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!desfazer.length} onClick={() => { const previous = desfazer.at(-1); setDesfazer(items => items.slice(0, -1)); setRefazer(items => [...items, edicoes]); setEdicoes(previous); setPrevia(null); setChaveIdempotencia(null); }}>Desfazer</Button><Button variant="outline" disabled={!refazer.length} onClick={() => { const next = refazer.at(-1); setRefazer(items => items.slice(0, -1)); setDesfazer(items => [...items, edicoes]); setEdicoes(next); setPrevia(null); setChaveIdempotencia(null); }}>Refazer</Button><Button variant="outline" onClick={() => { setEdicoes({}); setDesfazer([]); setRefazer([]); setPrevia(null); setChaveIdempotencia(null); }}>Descartar edições</Button><Button variant="outline" onClick={revisar} disabled={!Object.keys(edicoes).length}>Revisar alterações</Button>{previa && <><span className="self-center text-sm">Revisão: {resumo.inclusoes} inclusões, {resumo.alteracoes} alterações e {resumo.remocoes} remoções em {new Set(Object.values(edicoes).map(op => op.produto_id)).size} produtos.</span><Button onClick={salvar} disabled={!chaveIdempotencia}>Confirmar e salvar</Button></>}</div>
    </div>}
    <Link className="text-sm underline" to="/produtos">Voltar aos produtos</Link>
  </div>;
}
