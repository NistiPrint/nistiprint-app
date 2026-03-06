import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import PageHeader from '@/components/ui/PageHeader';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { estoqueService } from '@/services/EstoqueService';
import { AlertCircle, Package, Truck, Warehouse, ArrowUpRight, ArrowDownRight, Shuffle } from 'lucide-react';
import { useEffect, useState } from 'react';
import ProductDisplay from '@/components/ui/ProductDisplay';

function EstoqueDashboardPage() {
  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchDashboardData = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await estoqueService.getDashboardData();
        setDashboardData(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  if (loading) return <div className="text-center py-4">Carregando Dashboard de Estoque...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar dashboard: {error}</div>;

  // Calcular métricas
  const calcularMetricas = () => {
    if (!dashboardData) return {};

    const valorTotal = dashboardData.deposito_summary?.reduce((sum, dep) => sum + (dep.valor_total || 0), 0) || 0;
    const totalItens = dashboardData.posicao_estoque?.reduce((sum, pos) => sum + (pos.quantidade || 0), 0) || 0;
    const totalAlertas = dashboardData.alertas?.length || 0;

    return { valorTotal, totalItens, totalAlertas };
  };

  const metricas = calcularMetricas();

  return (
    <div className="container mx-auto py-8">
      <PageHeader
        title="Dashboard de Estoque"
        icon={Warehouse}
      />

      {/* Métricas Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <Card className="bg-blue-50 border-blue-200">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Valor Total em Estoque</CardTitle>
            <Warehouse className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-900">
              {metricas.valorTotal.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-green-50 border-green-200">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total de Itens Físicos</CardTitle>
            <Package className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-900">
              {metricas.totalItens.toLocaleString('pt-BR')}
            </div>
          </CardContent>
        </Card>

        <Card className={`${metricas.totalAlertas > 0 ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'}`}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Produtos com Estoque Baixo</CardTitle>
            <AlertCircle className={`h-4 w-4 ${metricas.totalAlertas > 0 ? 'text-red-600' : 'text-gray-600'}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${metricas.totalAlertas > 0 ? 'text-red-900' : 'text-gray-900'}`}>
              {metricas.totalAlertas}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Alerts */}
      {dashboardData.alertas && dashboardData.alertas.length > 0 && (
        <Card className="mb-6 border-l-4 border-red-500 bg-red-50 shadow-sm">
          <CardHeader>
            <CardTitle className="text-red-700 flex items-center gap-2">
              <AlertCircle className="h-5 w-5" /> Alertas de Estoque Baixo
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc pl-5 text-red-600">
              {dashboardData.alertas.map((alerta, index) => (
                <li key={index} className="border-b border-red-100 pb-2 last:border-0 last:pb-0">
                  Produto: {dashboardData.prefetched_products?.[alerta.produto_id]?.nome ||
                           dashboardData.prefetched_products?.[alerta.produto_id]?.name ||
                           alerta.produto_id},
                  Depósito: {dashboardData.prefetched_depositos?.[alerta.deposito_id]?.name || alerta.deposito_id},
                  Saldo Atual: {alerta.saldo_atual}, Mínimo: {alerta.estoque_minimo}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Summary by Warehouse */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Warehouse className="h-5 w-5" /> Resumo por Depósito
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Depósito</TableHead>
                <TableHead>Total de Produtos</TableHead>
                <TableHead className="text-right">Valor Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dashboardData.deposito_summary.map((summary, index) => (
                <TableRow key={index}>
                  <TableCell>{summary.deposito.name}</TableCell>
                  <TableCell>{summary.total_produtos}</TableCell>
                  <TableCell className="text-right">
                    {summary.valor_total.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Recent Movements */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Truck className="h-5 w-5" /> Últimas Movimentações
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Data</TableHead>
                <TableHead>Produto</TableHead>
                <TableHead>Setor Responsável</TableHead>
                <TableHead>Depósito</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead className="text-right">Quantidade</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dashboardData.movimentacoes && dashboardData.movimentacoes.length > 0 ? (
                dashboardData.movimentacoes.map((mov, index) => {
                  // Formatação da data - tenta diferentes formatos
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
                    } else if (mov.created_at) {
                      const data = mov.created_at.toDate ? mov.created_at.toDate() : new Date(mov.created_at);
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
                    if (tipo.includes('ENTRADA') || tipo.includes('SAIDA_RESERVA') || tipo.includes('TRANSFERENCIA_ENTRADA')) return 'bg-green-100 text-green-800';
                    if (tipo.includes('SAIDA') || tipo.includes('TRANSFERENCIA_SAIDA')) return 'bg-red-100 text-red-800';
                    if (tipo.includes('BALANCO')) return 'bg-blue-100 text-blue-800';
                    return 'bg-gray-100 text-gray-800';
                  };

                  // Ícone para tipo de movimento
                  const getIcon = (tipo) => {
                    if (tipo.includes('ENTRADA') || tipo.includes('TRANSFERENCIA_ENTRADA')) return <ArrowUpRight className="h-3 w-3 mr-1" />;
                    if (tipo.includes('SAIDA') || tipo.includes('TRANSFERENCIA_SAIDA')) return <ArrowDownRight className="h-3 w-3 mr-1" />;
                    if (tipo.includes('BALANCO')) return <Shuffle className="h-3 w-3 mr-1" />;
                    return <Package className="h-3 w-3 mr-1" />;
                  };

                  return (
                    <TableRow key={index}>
                      <TableCell className="text-sm">{dataFormatada}</TableCell>
                      <TableCell>
                        <ProductDisplay
                          product={dashboardData.prefetched_products?.[mov.produto_id]}
                          productId={mov.produto_id}
                        />
                      </TableCell>
                      <TableCell>
                        {dashboardData.prefetched_products?.[mov.produto_id]?.setor_responsavel_nome || '-'}
                      </TableCell>
                      <TableCell>
                        {dashboardData.prefetched_depositos?.[mov.deposito_id]?.name || mov.deposito_id}
                      </TableCell>
                      <TableCell>
                        <span className={`flex items-center px-2 py-1 rounded-full text-xs font-medium ${getBadgeColor(mov.tipo_movimento)}`}>
                          {getIcon(mov.tipo_movimento)}
                          {mov.tipo_movimento}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {Math.abs(mov.quantidade).toLocaleString('pt-BR')}
                      </TableCell>
                    </TableRow>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    Nenhuma movimentação encontrada
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default EstoqueDashboardPage;
