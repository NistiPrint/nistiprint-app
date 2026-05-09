import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import ProductSelector from '@/components/ui/ProductSelector';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { estoqueService } from '@/services/EstoqueService';
import { Box, ChevronDown, ChevronRight, Filter, History, Layers, List, Package, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

const TIPO_BLOCO_LABEL = {
  FINALIZACAO: { label: 'Finalização', color: 'bg-emerald-100 text-emerald-800' },
  JIT:         { label: 'Produção JIT', color: 'bg-amber-100 text-amber-800' },
  CONSUMO:     { label: 'Consumo', color: 'bg-slate-100 text-slate-700' },
};

function formatQty(value) {
  const n = Number(value || 0);
  // Inteiro -> sem casas; fracionário -> até 4 casas, sem zeros à direita
  if (Number.isInteger(n)) return n.toLocaleString('pt-BR');
  return n.toLocaleString('pt-BR', { maximumFractionDigits: 4 });
}

function tipoMovimentoBadge(tipo = '') {
  if (tipo === 'PROD_ACAB') return 'bg-emerald-200 text-emerald-900';
  if (tipo === 'PROD_INT')  return 'bg-amber-200 text-amber-900';
  if (tipo.startsWith('CONS')) return 'bg-rose-100 text-rose-800';
  if (tipo === 'AJUSTE') return 'bg-blue-100 text-blue-800';
  return 'bg-gray-100 text-gray-800';
}

function EstoqueHistoricoPage() {
  // Visões: 'consolidado' (default, blocos por correlation_id+estagio) ou 'bruto' (todas movimentações)
  const [viewMode, setViewMode] = useState('consolidado');

  const [blocos, setBlocos] = useState([]);
  const [movimentacoes, setMovimentacoes] = useState([]);
  const [depositos, setDepositos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [searchParams, setSearchParams] = useSearchParams();

  const filtroProdutoId = searchParams.get('produto_id') || 'all';
  const filtroDepositoId = searchParams.get('deposito_id') || 'all';
  const filtroTipoMovimento = searchParams.get('tipo_movimento') || 'all';
  const filtroTipoBloco = searchParams.get('tipo_bloco') || 'all';
  const filtroDataInicio = searchParams.get('data_inicio') ? new Date(searchParams.get('data_inicio')) : null;
  const filtroDataFim = searchParams.get('data_fim') ? new Date(searchParams.get('data_fim')) : null;

  useEffect(() => {
    let cancelled = false;
    const fetchHistorico = async () => {
      setLoading(true);
      setError(null);
      try {
        const filters = {};
        if (filtroProdutoId !== 'all') filters.produto_id = filtroProdutoId;
        if (filtroDepositoId !== 'all') filters.deposito_id = filtroDepositoId;
        if (filtroDataInicio) filters.data_inicio = filtroDataInicio.toISOString().split('T')[0];
        if (filtroDataFim) filters.data_fim = filtroDataFim.toISOString().split('T')[0];

        if (viewMode === 'consolidado') {
          if (filtroTipoBloco !== 'all') filters.tipo_bloco = filtroTipoBloco;
          const data = await estoqueService.getHistoricoConsolidado(filters);
          if (cancelled) return;
          setBlocos(data.blocos || []);
          setDepositos(data.depositos || []);
        } else {
          if (filtroTipoMovimento !== 'all') filters.tipo_movimento = filtroTipoMovimento;
          const data = await estoqueService.getHistorico(filters);
          if (cancelled) return;
          setMovimentacoes(data.movimentacoes || []);
          setDepositos(data.depositos || []);
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchHistorico();
    return () => { cancelled = true; };
  }, [viewMode, filtroProdutoId, filtroDepositoId, filtroTipoMovimento, filtroTipoBloco, filtroDataInicio, filtroDataFim]);

  // Agrupamento client-side só na visão "bruto" (legado).
  const groupedMovimentacoes = useMemo(() => {
    if (viewMode !== 'bruto') return [];
    const groups = {};
    movimentacoes.forEach(mov => {
      const ref = mov.correlation_id || mov.documento_referencia || 'SEM_REFERENCIA';
      if (!groups[ref]) {
        groups[ref] = {
          ref,
          correlation_id: mov.correlation_id,
          items: [],
          firstData: mov.data_movimentacao,
          motivo: mov.motivo || 'Diversos',
        };
      }
      groups[ref].items.push(mov);
      if (new Date(mov.data_movimentacao) < new Date(groups[ref].firstData)) {
        groups[ref].firstData = mov.data_movimentacao;
      }
    });
    return Object.values(groups).sort((a, b) => new Date(b.firstData) - new Date(a.firstData));
  }, [movimentacoes, viewMode]);

  const toggleGroup = (key) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleFilterChange = (key, value) => {
    setSearchParams(prev => {
      if (value && value !== 'all') prev.set(key, value);
      else prev.delete(key);
      return prev;
    }, { replace: true });
  };

  const handleClearFilters = () => {
    setSearchParams({}, { replace: true });
  };

  const movementTypes = [
    { value: 'ENTRADA', label: 'Entrada' },
    { value: 'SAIDA', label: 'Saída' },
    { value: 'BALANCO', label: 'Balanço' },
    { value: 'TRANSFERENCIA_ENTRADA', label: 'Transferência Entrada' },
    { value: 'TRANSFERENCIA_SAIDA', label: 'Transferência Saída' },
  ];
  const blocoTypes = [
    { value: 'FINALIZACAO', label: 'Finalização' },
    { value: 'JIT', label: 'Produção JIT' },
    { value: 'CONSUMO', label: 'Consumo' },
  ];

  const getDepositName = (id) => depositos.find(d => d.id === id)?.name || depositos.find(d => d.id === id)?.nome || id;

  return (
    <div className="container mx-auto py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Histórico de Movimentações</h1>
        <div className="inline-flex rounded-md border bg-muted p-0.5">
          <Button
            variant={viewMode === 'consolidado' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setViewMode('consolidado')}
            className="gap-2"
          >
            <Layers className="h-4 w-4" /> Consolidada
          </Button>
          <Button
            variant={viewMode === 'bruto' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => setViewMode('bruto')}
            className="gap-2"
          >
            <List className="h-4 w-4" /> Movimentos brutos
          </Button>
        </div>
      </div>

      <Card className="mb-6 shadow-sm">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg font-semibold">
            <Filter className="h-5 w-5 text-primary" /> Filtros de Pesquisa
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase">Produto</label>
              <ProductSelector
                value={filtroProdutoId !== 'all' ? filtroProdutoId : ''}
                onChange={(value) => handleFilterChange('produto_id', value || 'all')}
                placeholder="Filtrar por SKU ou Nome..."
              />
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase">Depósito</label>
              <Select value={filtroDepositoId} onValueChange={(value) => handleFilterChange('deposito_id', value)}>
                <SelectTrigger><SelectValue placeholder="Todos os depósitos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os depósitos</SelectItem>
                  {depositos.map(dep => <SelectItem key={dep.id} value={dep.id}>{dep.name || dep.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase">
                {viewMode === 'consolidado' ? 'Tipo de bloco' : 'Tipo'}
              </label>
              {viewMode === 'consolidado' ? (
                <Select value={filtroTipoBloco} onValueChange={(value) => handleFilterChange('tipo_bloco', value)}>
                  <SelectTrigger><SelectValue placeholder="Todos os tipos" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos os tipos</SelectItem>
                    {blocoTypes.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <Select value={filtroTipoMovimento} onValueChange={(value) => handleFilterChange('tipo_movimento', value)}>
                  <SelectTrigger><SelectValue placeholder="Todos os tipos" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos os tipos</SelectItem>
                    {movementTypes.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="flex items-end">
              <Button onClick={handleClearFilters} variant="outline" className="w-full">
                <Search className="h-4 w-4 mr-2" /> Limpar Filtros
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {loading && <div className="text-center py-10">Carregando...</div>}
      {error && <div className="text-center py-10 text-red-500">Erro: {error}</div>}

      {!loading && !error && viewMode === 'consolidado' && (
        <Card className="shadow-lg">
          <CardHeader className="bg-muted/30 border-b">
            <CardTitle className="flex items-center gap-2 text-xl">
              <History className="h-5 w-5 text-primary" /> Visão consolidada por evento de produção
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {blocos.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground italic">
                Nenhum bloco de movimentação encontrado.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead className="w-10"></TableHead>
                      <TableHead className="font-bold">Quando</TableHead>
                      <TableHead className="font-bold">Evento</TableHead>
                      <TableHead className="font-bold">Demanda</TableHead>
                      <TableHead className="text-right font-bold">Movimentos</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {blocos.map((bloco) => {
                      const key = `${bloco.correlation_id}_${bloco.estagio}`;
                      const isExpanded = expandedGroups[key] || false;
                      const dataFmt = new Date(bloco.data_inicio).toLocaleString('pt-BR');
                      const tipoMeta = TIPO_BLOCO_LABEL[bloco.tipo_bloco] || TIPO_BLOCO_LABEL.CONSUMO;

                      return (
                        <>
                          <TableRow
                            key={key}
                            className="hover:bg-muted/20 cursor-pointer border-l-4 border-l-primary/40 bg-gray-50/40"
                            onClick={() => toggleGroup(key)}
                          >
                            <TableCell>
                              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </TableCell>
                            <TableCell className="text-xs whitespace-nowrap">{dataFmt}</TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                <Package className="h-4 w-4 text-primary" />
                                <div>
                                  <span className="font-bold text-sm">{bloco.titulo}</span>
                                  <p className="text-[11px] text-muted-foreground">
                                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold mr-2 ${tipoMeta.color}`}>
                                      {tipoMeta.label}
                                    </span>
                                    Estágio: <span className="font-mono">{bloco.estagio}</span>
                                  </p>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="text-xs">
                              {bloco.demanda_codigo ? (
                                <div>
                                  <div className="font-semibold">{bloco.demanda_codigo}</div>
                                  <div className="text-muted-foreground truncate max-w-[200px]">
                                    {bloco.demanda_descricao || '-'}
                                  </div>
                                </div>
                              ) : (
                                <span className="text-muted-foreground italic">avulsa</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right font-bold">{bloco.total_movimentos}</TableCell>
                          </TableRow>

                          {isExpanded && (bloco.movimentos || []).map((m, idx) => (
                            <TableRow key={`${key}-${m.id || idx}`} className="bg-white hover:bg-muted/5">
                              <TableCell></TableCell>
                              <TableCell className="text-[10px] text-gray-400 whitespace-nowrap">
                                {new Date(m.data).toLocaleTimeString('pt-BR')}
                              </TableCell>
                              <TableCell className="pl-8">
                                <div className="flex flex-col">
                                  <span className="font-medium text-sm">
                                    {m.produto_nome || `SKU ${m.produto_id}`}
                                  </span>
                                  <span className="text-[10px] text-muted-foreground">
                                    Depósito: {getDepositName(m.deposito_id)} · Saldo: {formatQty(m.saldo_antes)} → {formatQty(m.saldo_depois)}
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell colSpan={2} className="text-right">
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-black mr-2 ${tipoMovimentoBadge(m.tipo)}`}>
                                  {m.tipo}
                                </span>
                                <span className="font-black text-sm">
                                  {Number(m.quantidade) > 0 ? '+' : ''}{formatQty(m.quantidade)}
                                </span>
                                {m.motivo && (
                                  <div className="text-[10px] italic text-muted-foreground truncate max-w-[300px] inline-block ml-2 align-middle">
                                    {m.motivo}
                                  </div>
                                )}
                              </TableCell>
                            </TableRow>
                          ))}
                        </>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!loading && !error && viewMode === 'bruto' && (
        <Card className="shadow-lg">
          <CardHeader className="bg-muted/30 border-b">
            <CardTitle className="flex items-center gap-2 text-xl">
              <History className="h-5 w-5 text-primary" /> Movimentos brutos
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {groupedMovimentacoes.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground italic">
                Nenhuma movimentação encontrada.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead className="w-10"></TableHead>
                      <TableHead className="font-bold">Data/Hora</TableHead>
                      <TableHead className="font-bold">Origem / Demanda</TableHead>
                      <TableHead className="text-right font-bold">Total</TableHead>
                      <TableHead className="font-bold">Responsável</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {groupedMovimentacoes.map((group) => {
                      const isExpanded = expandedGroups[group.ref] || false;
                      const dataFormatada = new Date(group.firstData).toLocaleString('pt-BR');
                      const hasRef = group.ref !== 'SEM_REFERENCIA';
                      return (
                        <>
                          <TableRow
                            key={group.ref}
                            className="hover:bg-muted/20 cursor-pointer border-l-4 border-l-primary/40 bg-gray-50/50"
                            onClick={() => toggleGroup(group.ref)}
                          >
                            <TableCell>
                              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            </TableCell>
                            <TableCell className="font-medium text-xs">{dataFormatada}</TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                {hasRef ? <Package className="h-4 w-4 text-primary" /> : <Box className="h-4 w-4 text-gray-400" />}
                                <div>
                                  <span className="font-bold text-sm">
                                    {hasRef ? (group.correlation_id ? `Reconciliação ${group.ref.slice(0, 8)}` : `Demanda ${group.ref}`) : 'Movimentação avulsa'}
                                  </span>
                                  <p className="text-xs text-muted-foreground truncate max-w-md">{group.motivo}</p>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="text-right font-bold">{group.items.length}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {group.items[0]?.usuario_email || group.items[0]?.usuario_id || '-'}
                            </TableCell>
                          </TableRow>

                          {isExpanded && group.items.map((mov, idx) => (
                            <TableRow key={`${group.ref}-${idx}`} className="bg-white hover:bg-muted/5">
                              <TableCell></TableCell>
                              <TableCell className="text-[10px] text-gray-400">
                                {new Date(mov.data_movimentacao).toLocaleTimeString('pt-BR')}
                              </TableCell>
                              <TableCell className="pl-8">
                                <div className="flex flex-col">
                                  <span className="font-medium text-sm">{mov.produtos?.nome || mov.produto_nome || 'SKU ' + mov.produto_id}</span>
                                  <span className="text-[10px] text-muted-foreground">Depósito: {getDepositName(mov.deposito_id)}</span>
                                </div>
                              </TableCell>
                              <TableCell className="text-right">
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-black mr-2 ${tipoMovimentoBadge(mov.tipo_movimentacao)}`}>
                                  {mov.tipo_movimentacao}
                                </span>
                                <span className="font-black text-sm">
                                  {Number(mov.quantidade) > 0 ? '+' : ''}{formatQty(mov.quantidade)}
                                </span>
                              </TableCell>
                              <TableCell className="text-[10px] italic max-w-[150px] truncate">{mov.motivo}</TableCell>
                            </TableRow>
                          ))}
                        </>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default EstoqueHistoricoPage;
