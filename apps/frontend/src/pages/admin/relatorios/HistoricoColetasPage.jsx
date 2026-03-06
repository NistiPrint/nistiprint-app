import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Truck, Calendar, User, ShoppingBag, Package } from 'lucide-react';
import { toast } from 'sonner';

function HistoricoColetasPage() {
  const [coletas, setColetas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchHistorico = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/v2/demanda_producao/coletas/historico', {
          headers: {
            'Accept': 'application/json'
          }
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (data.success) {
          setColetas(data.coletas || []);
        } else {
          throw new Error(data.message || 'Erro ao carregar coletas');
        }
      } catch (e) {
        setError(e.message);
        toast.error(`Erro ao carregar histórico de coletas: ${e.message}`);
      } finally {
        setLoading(false);
      }
    };

    fetchHistorico();
  }, []);

  if (loading) return <div className="text-center py-10 text-muted-foreground">Carregando Histórico de Coletas...</div>;
  if (error) return <div className="text-center py-10 text-red-500 font-medium">Erro ao carregar histórico: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <div className="flex items-center gap-3 mb-8">
        <Truck className="h-8 w-8 text-primary" />
        <h1 className="text-3xl font-bold">Histórico de Coletas</h1>
      </div>

      <Card className="shadow-lg border-2">
        <CardHeader className="bg-muted/50 border-b">
          <CardTitle className="flex items-center gap-2 text-xl">
            <Calendar className="h-5 w-5 text-primary" /> Registros Recentes (Últimos 200)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {coletas.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground italic">
              Nenhum registro de coleta encontrado no sistema.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="w-[180px] font-bold">Data/Hora</TableHead>
                    <TableHead className="font-bold">Demanda / Descrição</TableHead>
                    <TableHead className="font-bold">Plataforma</TableHead>
                    <TableHead className="font-bold">Pedido Ref.</TableHead>
                    <TableHead className="text-right font-bold">Qtd. Coletada</TableHead>
                    <TableHead className="font-bold">Usuário</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {coletas.map((coleta) => {
                    const demandInfo = coleta.demandas_producao || {};
                    const canalNome = demandInfo.canal_venda?.nome || '-';
                    
                    return (
                      <TableRow key={coleta.id} className="hover:bg-muted/10 transition-colors">
                        <TableCell className="font-medium text-gray-600">
                          {coleta.created_at ? new Date(coleta.created_at).toLocaleString('pt-BR') : '-'}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-bold text-gray-900">{demandInfo.descricao || 'Demanda s/ nome'}</span>
                            <span className="text-xs text-muted-foreground">ID: {coleta.demanda_id}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                            <ShoppingBag className="h-3 w-3 mr-1" /> {canalNome}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs font-semibold">
                          {demandInfo.pedido_numero || '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Badge variant="secondary" className="text-sm font-black px-3 py-0.5 bg-green-100 text-green-800">
                            {coleta.quantidade} un
                          </Badge>
                        </TableCell>
                        <TableCell className="text-gray-600 italic text-sm">
                          <div className="flex items-center gap-1">
                            <User className="h-3 w-3" /> {coleta.user_id || '-'}
                          </div>
                        </TableCell>
                      </TableRow>
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

export default HistoricoColetasPage;
