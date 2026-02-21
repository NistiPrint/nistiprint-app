import React, { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Loader2, History, ChevronLeft, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';

function HistoricoProducaoPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [has_next, setHasNext] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const currentPage = parseInt(searchParams.get('page')) || 1;

  useEffect(() => {
    const fetchHistorico = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/v2/relatorios/historico-producao?page=${currentPage}`, {
          headers: {
            'Accept': 'application/json'
          }
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        setLogs(data.logs || []);
        setHasNext(data.has_next);
      } catch (e) {
        setError(e.message);
        toast.error(`Erro ao carregar histórico de produção: ${e.message}`);
      } finally {
        setLoading(false);
      }
    };

    fetchHistorico();
  }, [currentPage]);

  const handlePageChange = (newPage) => {
    setSearchParams(prev => {
      prev.set('page', newPage);
      return prev;
    }, { replace: true });
  };

  if (loading) return <div className="text-center py-4">Carregando Histórico de Produção...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar histórico: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Histórico de Produção</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" /> Registros de Produção
          </CardTitle>
        </CardHeader>
        <CardContent>
          {logs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhum registro de produção encontrado.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead>Ordem Produção</TableHead>
                  <TableHead>Produto</TableHead>
                  <TableHead>Componente</TableHead>
                  <TableHead className="text-right">Quantidade Produzida</TableHead>
                  <TableHead>Usuário</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log, index) => (
                  <TableRow key={index}>
                    <TableCell>{log.timestamp ? new Date(log.timestamp).toLocaleString() : '-'}</TableCell>
                    <TableCell>{log.ordem_producao_id || '-'}</TableCell>
                    <TableCell>{log.produto_nome || log.produto_id || '-'}</TableCell> {/* Mostra nome do produto se disponível */}
                    <TableCell>{log.componente_id || '-'}</TableCell> {/* Pode não estar presente em todos os registros */}
                    <TableCell className="text-right">{log.quantidade_produzida || 0}</TableCell>
                    <TableCell>{log.user_email || log.usuario_id || log.equipe_nome || '-'}</TableCell> {/* Prioriza email do usuário */}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          <div className="flex items-center justify-between space-x-2 py-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              <ChevronLeft className="h-4 w-4 mr-2" /> Anterior
            </Button>
            <span className="text-sm text-muted-foreground">Página {currentPage}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={!has_next}
            >
              Próxima <ChevronRight className="h-4 w-4 ml-2" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default HistoricoProducaoPage;
