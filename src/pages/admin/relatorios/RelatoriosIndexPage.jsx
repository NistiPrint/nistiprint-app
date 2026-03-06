import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Database, History, LineChart, Package, Settings, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

function RelatoriosIndexPage() {
  const [sulfiteReport, setSulfiteReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processingQueue, setProcessingQueue] = useState(false);
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
      } catch (e) {
        setError(e.message);
        toast.error(`Erro ao carregar relatório de sulfite: ${e.message}`);
      } finally {
        setLoading(false);
      }
    };

    fetchSulfiteReport();
  }, []);

  const handleProcessQueue = async () => {
    setProcessingQueue(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/processar-fila-estoque', {
        method: 'POST'
      });
      const data = await response.json();
      if (data.success) {
        if (data.processed_count > 0) {
          toast.success(`${data.processed_count} tarefas de estoque processadas com sucesso!`);
        } else {
          toast.info('Nenhuma tarefa pendente na fila de estoque.');
        }
      } else {
        toast.error('Erro ao processar fila: ' + data.message);
      }
    } catch (e) {
      toast.error('Erro na requisição: ' + e.message);
    } finally {
      setProcessingQueue(false);
    }
  };

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
              <Settings className="h-5 w-5 text-primary" /> Manutenção de Estoque
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Link to="/relatorios/fila-estoque" className="flex items-center justify-between p-3 rounded-lg border hover:bg-muted/50 transition-colors">
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-purple-500" />
                <span className="font-medium">Fila de Estoque</span>
              </div>
              <span className="text-xs text-muted-foreground">Processar baixas</span>
            </Link>
          </CardContent>
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LineChart className="h-5 w-5 text-primary" /> Consumo de Insumos
            </CardTitle>
          </CardHeader>
          <CardContent>
            {sulfiteReport ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Mês/Ano</TableHead>
                    <TableHead className="text-right">A4</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(sulfiteReport).map(([period, consumption]) => (
                    <TableRow key={period}>
                      <TableCell>{period}</TableCell>
                      <TableCell className="text-right">{consumption}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                Nenhum dado disponível.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default RelatoriosIndexPage;
