import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import ProductionService from '@/services/ProductionService';
import { ArrowLeft, BarChart3, Layers, LayoutGrid, Package } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const ResumoProducaoPage = () => {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const response = await ProductionService.getDailySummary();
      if (response.success) {
        setSummary(response.summary);
      } else {
        toast.error('Erro ao carregar resumo da produção.');
      }
    } catch (error) {
      toast.error('Erro de comunicação com o servidor.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSummary();
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="container mx-auto p-4 space-y-8">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Resumo da Produção Diária</h1>
          <p className="text-muted-foreground mt-1">Estado atual de todas as demandas ativas</p>
          <p className="text-sm text-gray-600 mt-2">Data: {new Date().toLocaleDateString('pt-BR')}</p>
        </div>
        <Link to="/producao">
          <Button variant="ghost" className="flex items-center gap-2">
            <ArrowLeft className="h-4 w-4" />
            Voltar ao Painel
          </Button>
        </Link>
      </div>

      {/* Quadro Total Geral */}
      <Card className="border-blue-200 shadow-sm">
        <CardHeader className="bg-blue-50/50">
          <CardTitle className="flex items-center gap-2 text-blue-800 text-lg">
            <LayoutGrid className="h-5 w-5" /> Quadro Total Geral
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-4 bg-white border rounded-lg shadow-sm">
              <div className="text-xs font-bold text-gray-500 uppercase">Itens a Produzir</div>
              <div className="text-2xl font-black text-gray-900">{summary.geral.total_produzir}</div>
              <div className="text-[10px] text-gray-400 mt-1">Soma de todas as quantidades</div>
            </div>
            <div className="p-4 bg-white border rounded-lg shadow-sm">
              <div className="text-xs font-bold text-gray-500 uppercase">Itens Restantes</div>
              <div className="text-2xl font-black text-blue-600">{summary.geral.total_restante}</div>
              <div className="text-[10px] text-gray-400 mt-1">Total - Finalizados</div>
            </div>
            <div className="p-4 bg-white border rounded-lg shadow-sm">
              <div className="text-xs font-bold text-gray-500 uppercase">Capas Restantes</div>
              <div className="text-2xl font-black text-orange-600">{summary.geral.total_capas_restantes}</div>
              <div className="text-[10px] text-gray-400 mt-1">Total - Capas entregues</div>
            </div>
            <div className="p-4 bg-white border rounded-lg shadow-sm">
              <div className="text-xs font-bold text-gray-500 uppercase">Miolos (Entregues / Restantes)</div>
              <div className="text-2xl font-black flex items-baseline gap-2">
                {summary.geral.total_miolos_restantes === 0 ? (
                  <span className="text-green-600">OK</span>
                ) : (
                  <>
                    <span className="text-green-600">{summary.geral.total_miolos_entregues}</span>
                    <span className="text-gray-300 text-sm">/</span>
                    <span className="text-purple-600">{summary.geral.total_miolos_restantes}</span>
                  </>
                )}
              </div>
              <div className="text-[10px] text-gray-400 mt-1">Entregues = Prontos para Retirar</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Quadro Total por Plataforma */}
      <Card className="border-indigo-200 shadow-sm">
        <CardHeader className="bg-indigo-50/50">
          <CardTitle className="flex items-center gap-2 text-indigo-800 text-lg">
            <BarChart3 className="h-5 w-5" /> Quadro Total por Plataforma
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 px-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-gray-50/50">
                <TableHead className="font-bold pl-6">Plataforma</TableHead>
                <TableHead className="text-center font-bold">Total a Produzir</TableHead>
                <TableHead className="text-center font-bold">Itens Restantes</TableHead>
                <TableHead className="text-center font-bold">Capas Restantes</TableHead>
                <TableHead className="text-center font-bold">Miolos (Ent/Rest)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(summary.por_plataforma).map(([plataforma, stats]) => (
                <TableRow key={plataforma}>
                  <TableCell className="font-medium pl-6">{plataforma}</TableCell>
                  <TableCell className="text-center">{stats.total_produzir}</TableCell>
                  <TableCell className="text-center text-blue-600 font-bold">{stats.total_restante}</TableCell>
                  <TableCell className="text-center text-orange-600 font-bold">{stats.total_capas_restantes}</TableCell>
                  <TableCell className="text-center">
                    {stats.total_miolos_restantes === 0 ? (
                      <span className="text-green-600 font-bold">OK</span>
                    ) : (
                      <>
                        <span className="text-green-600 font-bold">{stats.total_miolos_entregues}</span>
                        <span className="text-gray-300 mx-1">/</span>
                        <span className="text-purple-600 font-bold">{stats.total_miolos_restantes}</span>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Quadro Total por Setor */}
      <Card className="border-emerald-200 shadow-sm">
        <CardHeader className="bg-emerald-50/50">
          <CardTitle className="flex items-center gap-2 text-emerald-800 text-lg">
            <Layers className="h-5 w-5" /> Quadro Total por Setor
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {Object.entries(summary.por_setor).map(([setor, stats]) => (
              <div key={setor} className="space-y-4">
                <div className="flex items-center gap-2 border-b pb-2">
                  <Package className="h-4 w-4 text-emerald-600" />
                  <span className="font-bold text-gray-700">{setor}</span>
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500 uppercase">Completos</span>
                    <Badge variant="secondary" className="bg-green-100 text-green-700 hover:bg-green-100 border-green-200">
                      {stats.completos}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500 uppercase">Em Andamento</span>
                    <Badge variant="secondary" className="bg-blue-100 text-blue-700 hover:bg-blue-100 border-blue-200">
                      {stats.em_andamento}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500 uppercase">Restantes</span>
                    <Badge variant="secondary" className="bg-gray-100 text-gray-700 hover:bg-gray-100 border-gray-200">
                      {stats.restantes}
                    </Badge>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default ResumoProducaoPage;
