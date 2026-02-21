import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import ProductSelector from '@/components/ui/ProductSelector';
import { estoqueService } from '@/services/EstoqueService';
import { Filter, History, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

function EstoqueHistoricoPage() {
  const [movimentacoes, setMovimentacoes] = useState([]);
  const [depositos, setDepositos] = useState([]);
  const [produtosDisponiveis, setProdutosDisponiveis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
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
        // Não precisamos mais armazenar produtos separadamente, pois já estão aninhados nas movimentações
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchHistorico();
  }, [filtroProdutoId, filtroDepositoId, filtroTipoMovimento, filtroDataInicio, filtroDataFim]);

  const handleFilterChange = (key, value) => {
    setSearchParams(prev => {
      if (value && value !== 'all') { // Check if value is not empty and not 'all'
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

  if (loading) return <div className="text-center py-4">Carregando Histórico de Movimentações...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar histórico: {error}</div>;

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

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Filter className="h-5 w-5" /> Filtros</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Produto</label>
              <ProductSelector
                value={filtroProdutoId !== 'all' ? filtroProdutoId : ''}
                onChange={(value) => handleFilterChange('produto_id', value || 'all')}
                placeholder="Buscar e filtrar produto..."
              />
            </div>

            <Select
              value={filtroDepositoId}
              onValueChange={(value) => handleFilterChange('deposito_id', value)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Todos os depósitos" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos os depósitos</SelectItem>
                {depositos.map(dep => (
                  <SelectItem key={dep.id} value={dep.id}>
                    {dep.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={filtroTipoMovimento}
              onValueChange={(value) => handleFilterChange('tipo_movimento', value)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Todos os tipos" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos os tipos</SelectItem>
                {movementTypes.map(type => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button onClick={handleClearFilters} variant="outline">
              <Search className="h-4 w-4 mr-2" /> Limpar Filtros
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" /> Registros de Movimentação
          </CardTitle>
        </CardHeader>
        <CardContent>
          {movimentacoes.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma movimentação encontrada com os filtros aplicados.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Data/Hora</TableHead>
                  <TableHead>Produto</TableHead>
                  <TableHead>Setor Responsável</TableHead>
                  <TableHead>Depósito</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead className="text-right">Quantidade</TableHead>
                  <TableHead>Observação</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {movimentacoes.map((mov, index) => {
                  // Formatação da data
                  let dataFormatada = 'N/A';
                  try {
                    if (mov.data_movimentacao) {
                      const data = mov.data_movimentacao.toDate ? mov.data_movimentacao.toDate() : new Date(mov.data_movimentacao);
                      dataFormatada = data.toLocaleString('pt-BR', {
                        day: '2-digit',
                        month: '2-digit',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      });
                    }
                  } catch (e) {
                    dataFormatada = 'Data inválida';
                  }

                  // Badge para tipo de movimento
                  const getBadgeColor = (tipo) => {
                    if (tipo.includes('ENTRADA')) return 'bg-green-100 text-green-800';
                    if (tipo.includes('SAIDA')) return 'bg-red-100 text-red-800';
                    if (tipo.includes('BALANCO')) return 'bg-blue-100 text-blue-800';
                    return 'bg-gray-100 text-gray-800';
                  };

                  return (
                    <TableRow key={index}>
                      <TableCell className="text-sm">{dataFormatada}</TableCell>
                      <TableCell className="font-medium">{mov.produtos?.nome || 'Produto não encontrado'}</TableCell>
                      <TableCell>
                        {mov.produtos?.setor_responsavel_nome || '-'}
                      </TableCell>
                      <TableCell>{getDepositName(mov.deposito_id || mov.deposito_origem_id)}</TableCell>
                      <TableCell>
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${getBadgeColor(mov.tipo_movimento)}`}>
                          {mov.tipo_movimento}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {Math.abs(mov.quantidade).toLocaleString('pt-BR')}
                      </TableCell>
                      <TableCell className="max-w-xs truncate" title={mov.motivo}>
                        {mov.motivo || '-'}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default EstoqueHistoricoPage;
