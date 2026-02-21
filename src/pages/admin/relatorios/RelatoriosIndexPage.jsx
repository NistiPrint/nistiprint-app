import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Package, LineChart } from 'lucide-react';
import { toast } from 'sonner';

function RelatoriosIndexPage() {
  const [sulfiteReport, setSulfiteReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchSulfiteReport = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/v2/relatorios', {
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

  if (loading) return <div className="text-center py-4">Carregando Relatórios...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar relatórios: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Relatórios</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LineChart className="h-5 w-5" /> Relatório de Consumo de Sulfite
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sulfiteReport ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mês/Ano</TableHead>
                  <TableHead className="text-right">Consumo (Folhas A4)</TableHead>
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
              Nenhum dado de consumo de sulfite disponível.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default RelatoriosIndexPage;
