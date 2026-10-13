import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Database, History, LineChart, Package, Settings, Truck, Webhook } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '@/contexts/AuthContext';

function RelatoriosIndexPage() {
  const { isAdmin } = useAuth();
  const [sulfiteReport, setSulfiteReport] = useState(null);
  const [sulfiteReportDetails, setSulfiteReportDetails] = useState({});
  const [sulfiteReportMetadata, setSulfiteReportMetadata] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchSulfiteReport = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/v2/relatorios/', {
          headers: {
            'Accept': 'application/json'
          }
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        setSulfiteReport(data.sulfite_report);
        setSulfiteReportDetails(data.sulfite_report_details || {});
        setSulfiteReportMetadata(data.sulfite_report_metadata || null);
      } catch (e) {
        setError(e.message);
        toast.error(`Erro ao carregar relatório de sulfite: ${e.message}`);
      } finally {
        setLoading(false);
      }
    };

    fetchSulfiteReport();
  }, []);

  if (loading) return <div className="text-center py-10">Carregando Relatórios...</div>;
  if (error) return <div className="text-center py-10 text-red-500">Erro ao carregar relatórios: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Relatórios e Históricos</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        <Card className="hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <History className="h-5 w-5 text-primary" /> Históricos de Operação
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Link to="/relatorios/historico-producao" className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
              <div className="flex items-center gap-3">
                <Package className="h-5 w-5 text-blue-500" />
                <span className="font-medium">Histórico de Produção</span>
              </div>
              <span className="text-xs text-muted-foreground">Fabricação</span>
            </Link>
            
            <Link to="/relatorios/historico-coletas" className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
              <div className="flex items-center gap-3">
                <Truck className="h-5 w-5 text-green-500" />
                <span className="font-medium">Histórico de Coletas</span>
              </div>
              <span className="text-xs text-muted-foreground">Saídas</span>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5 text-primary" /> Monitoramento de Estoque
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Link to="/relatorios/monitoramento-estoque" className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-purple-500" />
                <span className="font-medium">Monitoramento</span>
              </div>
              <span className="text-xs text-muted-foreground">Eventos e Fila</span>
            </Link>
            {isAdmin() && (
              <Link to="/relatorios/webhooks" className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
                <div className="flex items-center gap-3">
                  <Webhook className="h-5 w-5 text-blue-500" />
                  <span className="font-medium">Webhooks e exceções</span>
                </div>
                <span className="text-xs text-muted-foreground">Payloads, contas e SKUs</span>
              </Link>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LineChart className="h-5 w-5 text-primary" /> Consumo de Insumos
            </CardTitle>
          </CardHeader>
          <CardContent>
            {sulfiteReportMetadata && (
              <p className="mb-3 text-xs text-muted-foreground">
                Fonte: ledger de movimentos confirmados
                {sulfiteReportMetadata.period_start && ` · Período: ${sulfiteReportMetadata.period_start} a ${sulfiteReportMetadata.period_end}`}
                {sulfiteReportMetadata.generated_at && ` · Gerado em ${new Date(sulfiteReportMetadata.generated_at).toLocaleString('pt-BR')}`}
              </p>
            )}
            {sulfiteReportMetadata?.error && (
              <p className="mb-3 text-sm text-destructive" role="status">{sulfiteReportMetadata.error}</p>
            )}
            {sulfiteReport && Object.keys(sulfiteReport).length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mês/Ano</TableHead>
                    <TableHead className="text-right">A4</TableHead>
                    <TableHead>Movimentos de origem</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(sulfiteReport).map(([period, consumption]) => (
                    <TableRow key={period}>
                      <TableCell>{period}</TableCell>
                      <TableCell className="text-right">{consumption}</TableCell>
                      <TableCell>
                        <details>
                          <summary className="cursor-pointer">{sulfiteReportDetails[period]?.length || 0} movimentos</summary>
                          <ul className="mt-2 space-y-1 text-xs">
                            {(sulfiteReportDetails[period] || []).map((movement) => (
                              <li key={movement.movimento_id}>
                                #{movement.movimento_id} · {movement.tipo} · {movement.quantidade_liquida}
                                {movement.operation_id ? ` · operação ${movement.operation_id}` : ' · legado sem operation_id'}
                              </li>
                            ))}
                          </ul>
                        </details>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                {sulfiteReportMetadata?.error || 'Nenhum movimento de consumo confirmado no ledger para o produto configurado.'}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default RelatoriosIndexPage;
