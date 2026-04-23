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

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2"></div>
        <p className="text-muted-foreground">Carregando Dashboard de Estoque...</p>
      </div>
    </div>
  );
  
  if (error) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center text-red-500">
        <AlertCircle className="h-8 w-8 mx-auto mb-2" />
        <p>Erro ao carregar dashboard: {error}</p>
      </div>
    </div>
  );

  // Calcular métricas
  const calcularMetricas = () => {
    if (!dashboardData) return {};

    const valorTotal = dashboardData.deposito_summary?.reduce((sum, dep) => sum + (dep.valor_total || 0), 0) || 0;
    const totalItens = dashboardData.posicao_estoque?.reduce((sum, pos) => sum + (pos.quantidade || 0), 0) || 0;
    const totalAlertas = dashboardData.alertas?.length || 0;

    return { valorTotal, totalItens, totalAlertas };
  };

  const metricas = calcularMetricas();

  const metricCards = [
    {
      title: 'Valor Total em Estoque',
      value: metricas.valorTotal.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }),
      icon: Warehouse,
      color: 'text-blue-600',
      bgColor: 'bg-blue-50',
      borderColor: 'border-blue-200'
    },
    {
      title: 'Total de Itens Físicos',
      value: metricas.totalItens.toLocaleString('pt-BR'),
      icon: Package,
      color: 'text-green-600',
      bgColor: 'bg-green-50',
      borderColor: 'border-green-200'
    },
    {
      title: 'Produtos com Estoque Baixo',
      value: metricas.totalAlertas.toString(),
      icon: AlertCircle,
      color: metricas.totalAlertas > 0 ? 'text-red-600' : 'text-gray-600',
      bgColor: metricas.totalAlertas > 0 ? 'bg-red-50' : 'bg-gray-50',
      borderColor: metricas.totalAlertas > 0 ? 'border-red-200' : 'border-gray-200'
    }
  ];

  return (
    <div className="container mx-auto py-8 px-4 md:px-6">
      <PageHeader
        title="Dashboard de Estoque"
        icon={Warehouse}
        description="Visão geral do inventário e movimentações"
      />

      {/* Métricas Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        {metricCards.map((card, index) => {
          const Icon = card.icon;
          return (
            <Card key={index} className={`border-l-4 ${card.borderColor} shadow-sm hover:shadow-md transition-shadow`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {card.title}
                </CardTitle>
                <div className={`w-8 h-8 rounded-lg ${card.bgColor} flex items-center justify-center`}>
                  <Icon className={`h-4 w-4 ${card.color}`} />
                </div>
              </CardHeader>
              <CardContent>
                <div className={`text-2xl font-bold ${card.color}`}>
                  {card.value}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Alerts */}
      {dashboardData.alertas && dashboardData.alertas.length > 0 && (
        <Card className="mb-6 border-l-4 border-red-500 bg-red-50/50 shadow-sm">
          <CardHeader>
            <CardTitle className="text-red-700 flex items-center gap-2">
              <AlertCircle className="h-5 w-5" /> Alertas de Estoque Baixo
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc pl-5 text-red-600 space-y-2">
              {dashboardData.alertas.map((alerta, index) => (
                <li key={index} className="border-b border-red-100 pb-2 last:border-0 last:pb-0">
                  <span className="font-medium">
                    {dashboardData.prefetched_products?.[alerta.produto_id]?.nome ||
                     dashboardData.prefetched_products?.[alerta.produto_id]?.name ||
                     alerta.produto_id}
                  </span>
                  {' - Depósito: '}
                  <span className="font-medium">
                    {dashboardData.prefetched_depositos?.[alerta.deposito_id]?.name || alerta.deposito_id}
                  </span>
                  {', Saldo Atual: '}
                  <span className="font-bold">{alerta.saldo_atual}</span>
                  {', Mínimo: '}
                  <span className="font-bold">{alerta.estoque_minimo}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Summary by Warehouse */}
      <Card className="mb-6 shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Warehouse className="h-5 w-5 text-muted-foreground" /> Resumo por Depósito
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
                  <TableCell className="font-medium">{summary.deposito.name}</TableCell>
                  <TableCell>{summary.total_produtos}</TableCell>
                  <TableCell className="text-right font-medium">
                    {summary.valor_total.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Recent Movements */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Truck className="h-5 w-5 text-muted-foreground" /> Últimas Movimentações
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

                  const getBadgeColor = (tipo) => {
                    if (tipo.includes('ENTRADA') || tipo.includes('SAIDA_RESERVA') || tipo.includes('TRANSFERENCIA_ENTRADA')) return 'bg-green-100 text-green-800';
                    if (tipo.includes('SAIDA') || tipo.includes('TRANSFERENCIA_SAIDA')) return 'bg-red-100 text-red-800';
                    if (tipo.includes('BALANCO')) return 'bg-blue-100 text-blue-800';
                    return 'bg-gray-100 text-gray-800';
                  };

                  const getIcon = (tipo) => {
                    if (tipo.includes('ENTRADA') || tipo.includes('TRANSFERENCIA_ENTRADA')) return <ArrowUpRight className="h-3 w-3 mr-1" />;
                    if (tipo.includes('SAIDA') || tipo.includes('TRANSFERENCIA_SAIDA')) return <ArrowDownRight className="h-3 w-3 mr-1" />;
                    if (tipo.includes('BALANCO')) return <Shuffle className="h-3 w-3 mr-1" />;
                    return <Package className="h-3 w-3 mr-1" />;
                  };

                  return (
                    <TableRow key={index}>
                      <TableCell className="text-sm text-muted-foreground">{dataFormatada}</TableCell>
                      <TableCell>
                        <ProductDisplay
                          product={dashboardData.prefetched_products?.[mov.produto_id]}
                          productId={mov.produto_id}
                        />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {dashboardData.prefetched_products?.[mov.produto_id]?.setor_responsavel_nome || '-'}
                      </TableCell>
                      <TableCell className="font-medium">
                        {dashboardData.prefetched_depositos?.[mov.deposito_id]?.name || mov.deposito_id}
                      </TableCell>
                      <TableCell>
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${getBadgeColor(mov.tipo_movimento)}`}>
                          {getIcon(mov.tipo_movimento)}
                          {mov.tipo_movimento}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {Math.abs(mov.quantidade).toLocaleString('pt-BR')}
                      </TableCell>
                    </TableRow>
                  );
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                    <Package className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>Nenhuma movimentação encontrada</p>
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
