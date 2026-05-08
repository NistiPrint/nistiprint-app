import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import ProductSelector from '@/components/ui/ProductSelector';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { estoqueService } from '@/services/EstoqueService';
import { Box, ChevronDown, ChevronRight, Filter, History, Package, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

function EstoqueHistoricoPage() {
  const [movimentacoes, setMovimentacoes] = useState([]);
  const [depositos, setDepositos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [searchParams, setSearchParams] = useSearchParams();

  const filtroProdutoId = searchParams.get('produto_id') || 'all';
  const filtroDepositoId = searchParams.get('deposito_id') || 'all';
  const filtroTipoMovimento = searchParams.get('tipo_movimento') || 'all';
  const filtroDataInicio = searchParams.get('data_inicio') ? new Date(searchParams.get('data_inicio')) : null;
  const filtroDataFim = searchParams.get('data_fim') ? new Date(searchParams.get('data_fim')) : null;

  useEffect(() => {
    const fetchHistorico = async () => {
      setLoading(true);
      setError(null);
      try {
        const filters = {};
        if (filtroProdutoId !== 'all') filters.produto_id = filtroProdutoId;
        if (filtroDepositoId !== 'all') filters.deposito_id = filtroDepositoId;
        if (filtroTipoMovimento !== 'all') filters.tipo_movimento = filtroTipoMovimento;
        if (filtroDataInicio) filters.data_inicio = filtroDataInicio.toISOString().split('T')[0];
        if (filtroDataFim) filters.data_fim = filtroDataFim.toISOString().split('T')[0];

        const data = await estoqueService.getHistorico(filters);
        setMovimentacoes(data.movimentacoes || []);
        setDepositos(data.depositos || []);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchHistorico();
  }, [filtroProdutoId, filtroDepositoId, filtroTipoMovimento, filtroDataInicio, filtroDataFim]);

  // Agrupamento de movimentações por correlation_id (produção) ou documento_referencia (demanda)
  const groupedMovimentacoes = useMemo(() => {
    const groups = {};
    movimentacoes.forEach(mov => {
      // Prioriza correlation_id para agrupar movimentos relacionados (produção + componentes)
      // Se não tiver correlation_id, usa documento_referencia
      // Se não tiver nenhum, usa 'SEM_REFERENCIA'
      const ref = mov.correlation_id || mov.documento_referencia || 'SEM_REFERENCIA';
      if (!groups[ref]) {
        groups[ref] = {
          ref,
          correlation_id: mov.correlation_id,
          items: [],
          firstData: mov.data_movimentacao,
          motivo: mov.motivo || 'Diversos'
        };
      }
      groups[ref].items.push(mov);
      // Manter sempre a data mais antiga do grupo como "início"
      if (new Date(mov.data_movimentacao) < new Date(groups[ref].firstData)) {
        groups[ref].firstData = mov.data_movimentacao;
      }
    });

    // Pós-processamento: identifica a entrada raiz (produção principal) e o motivo do grupo.
    // A entrada raiz é a ENTRADA cuja motivação NÃO é gerada pela explosão de BOM
    // (ou seja, não tem "JIT", "Auto-produção" ou "Consumo componente"), com fallback para
    // a entrada cronologicamente mais antiga.
    Object.values(groups).forEach(group => {
      const entradas = group.items.filter(m => m.tipo_movimento === 'ENTRADA' && m.quantidade > 0);
      const isDerivado = (motivo = '') =>
        /JIT|auto-produ[cç][aã]o|consumo componente|consumo jit/i.test(motivo);
      const raiz =
        entradas.find(m => !isDerivado(m.motivo || '')) ||
        entradas.slice().sort((a, b) => new Date(a.data_movimentacao) - new Date(b.data_movimentacao))[0] ||
        null;
      group.entradaRaiz = raiz;
      if (raiz?.motivo) group.motivo = raiz.motivo;
    });

    return Object.values(groups).sort((a, b) => new Date(b.firstData) - new Date(a.firstData));
  }, [movimentacoes]);

  const toggleGroup = (ref) => {
    setExpandedGroups(prev => ({ ...prev, [ref]: !prev[ref] }));
  };

  const handleFilterChange = (key, value) => {
    setSearchParams(prev => {
      if (value && value !== 'all') {
        prev.set(key, value);
      } else {
        prev.delete(key);
      }
      return prev;
    }, { replace: true });
  };

  const handleClearFilters = () => {
    setSearchParams({}, { replace: true });
  };

  if (loading) return <div className="text-center py-10">Carregando Histórico de Movimentações...</div>;
  if (error) return <div className="text-center py-10 text-red-500">Erro ao carregar histórico: {error}</div>;

  const movementTypes = [
    { value: 'ENTRADA', label: 'Entrada' },
    { value: 'SAIDA', label: 'Saída' },
    { value: 'BALANCO', label: 'Balanço' },
    { value: 'TRANSFERENCIA_ENTRADA', label: 'Transferência Entrada' },
    { value: 'TRANSFERENCIA_SAIDA', label: 'Transferência Saída' },
  ];

  const getDepositName = (id) => depositos.find(d => d.id === id)?.name || id;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Histórico de Movimentações</h1>

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
                  {depositos.map(dep => <SelectItem key={dep.id} value={dep.id}>{dep.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-bold text-gray-500 uppercase">Tipo</label>
              <Select value={filtroTipoMovimento} onValueChange={(value) => handleFilterChange('tipo_movimento', value)}>
                <SelectTrigger><SelectValue placeholder="Todos os tipos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os tipos</SelectItem>
                  {movementTypes.map(type => <SelectItem key={type.value} value={type.value}>{type.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-end">
              <Button onClick={handleClearFilters} variant="outline" className="w-full">
                <Search className="h-4 w-4 mr-2" /> Limpar Filtros
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-lg">
        <CardHeader className="bg-muted/30 border-b">
          <CardTitle className="flex items-center gap-2 text-xl">
            <History className="h-5 w-5 text-primary" /> Registros Agrupados por Demanda
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
                    <TableHead className="font-bold">Informação da Origem / Demanda</TableHead>
                    <TableHead className="text-right font-bold">Total de Itens</TableHead>
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
                                  {group.correlation_id
                                    ? (() => {
                                        // Usa a entrada-raiz já identificada no agrupamento
                                        // (a produção que originou a cadeia, não o JIT intermediário).
                                        const raiz = group.entradaRaiz;
                                        if (raiz) {
                                          return `PRODUÇÃO: ${raiz.produtos?.nome || 'Produto ' + raiz.produto_id}`;
                                        }
                                        return 'PRODUÇÃO';
                                      })()
                                    : hasRef
                                      ? `DEMANDA: ${group.ref}`
                                      : 'MOVIMENTAÇÃO AVULSA'}
                                </span>
                                <p className="text-xs text-muted-foreground truncate max-w-md">{group.motivo}</p>
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-bold">
                            {group.items.length} movimentações
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {group.items[0]?.usuario_email || group.items[0]?.usuario_id || '-'}
                          </TableCell>
                        </TableRow>

                        {isExpanded && group.items.map((mov, idx) => {
                          const getBadgeColor = (tipo) => {
                            if (tipo.includes('ENTRADA')) return 'bg-green-100 text-green-800';
                            if (tipo.includes('SAIDA')) return 'bg-red-100 text-red-800';
                            if (tipo.includes('BALANCO')) return 'bg-blue-100 text-blue-800';
                            return 'bg-gray-100 text-gray-800';
                          };

                          return (
                            <TableRow key={`${group.ref}-${idx}`} className="bg-white hover:bg-muted/5 animate-in fade-in duration-200">
                              <TableCell></TableCell>
                              <TableCell className="text-[10px] text-gray-400">
                                {new Date(mov.data_movimentacao).toLocaleTimeString('pt-BR')}
                              </TableCell>
                              <TableCell className="pl-8">
                                <div className="flex flex-col">
                                  <span className="font-medium text-sm">{mov.produtos?.nome || 'SKU ' + mov.produto_id}</span>
                                  <span className="text-[10px] text-muted-foreground">Depósito: {getDepositName(mov.deposito_id)}</span>
                                </div>
                              </TableCell>
                              <TableCell className="text-right">
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-black mr-2 ${getBadgeColor(mov.tipo_movimento)}`}>
                                  {mov.tipo_movimento}
                                </span>
                                <span className="font-black text-sm">
                                  {mov.quantidade > 0 ? '+' : ''}{mov.quantidade.toLocaleString('pt-BR')} un
                                </span>
                              </TableCell>
                              <TableCell className="text-[10px] italic max-w-[150px] truncate">
                                {mov.motivo}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default EstoqueHistoricoPage;
