import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { estoqueService } from '@/services/EstoqueService';
import { BarChart3, PieChart, TrendingDown } from 'lucide-react';
import { useEffect, useState } from 'react';

function EstoqueRelatoriosPage() {
  const [abcData, setAbcData] = useState({ A: [], B: [], C: [] });
  const [valuationData, setValuationData] = useState({ items: [], total_geral: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchRelatorios = async () => {
      setLoading(true);
      try {
        const [abc, valuation] = await Promise.all([
          estoqueService.getRelatorioABC(30),
          estoqueService.getRelatorioValorizacao()
        ]);
        setAbcData(abc);
        setValuationData(valuation);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchRelatorios();
  }, []);

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
  };

  if (loading) return <div className="text-center py-4">Carregando Relatórios...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar relatórios: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Relatórios de Estoque</h1>

      <Tabs defaultValue="abc" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="abc" className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" /> Curva ABC (30 dias)
          </TabsTrigger>
          <TabsTrigger value="valuation" className="flex items-center gap-2">
            <PieChart className="h-4 w-4" /> Valorização de Estoque
          </TabsTrigger>
        </TabsList>

        <TabsContent value="abc">
          <Card>
            <CardHeader>
              <CardTitle>Análise Curva ABC</CardTitle>
              <p className="text-sm text-muted-foreground">
                Produtos classificados pelo impacto financeiro no consumo (Saídas x Custo).
              </p>
            </CardHeader>
            <CardContent>
              <div className="space-y-8">
                {['A', 'B', 'C'].map(classe => (
                  <div key={classe}>
                    <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                      Classe {classe} 
                      <span className="text-sm font-normal text-muted-foreground">
                        ({classe === 'A' ? '70% do Valor' : classe === 'B' ? '20% do Valor' : '10% do Valor'})
                      </span>
                    </h3>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>SKU</TableHead>
                          <TableHead>Produto</TableHead>
                          <TableHead>Setor Responsável</TableHead>
                          <TableHead className="text-right">Qtd Saída</TableHead>
                          <TableHead className="text-right">Valor Consumo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {abcData[classe]?.length > 0 ? abcData[classe].map((item, idx) => (
                          <TableRow key={idx}>
                            <TableCell className="font-mono">{item.sku}</TableCell>
                            <TableCell>{item.nome}</TableCell>
                            <TableCell>{item.setor_responsavel_nome || '-'}</TableCell>
                            <TableCell className="text-right">{item.quantidade}</TableCell>
                            <TableCell className="text-right">{formatCurrency(item.valor_total)}</TableCell>
                          </TableRow>
                        )) : (
                          <TableRow>
                            <TableCell colSpan={5} className="text-center text-muted-foreground">Nenhum produto nesta classe.</TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="valuation">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Valor Total em Estoque</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatCurrency(valuationData.total_geral)}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Itens com Saldo</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{valuationData.items.filter(i => i.saldo_atual > 0).length}</div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Detalhamento de Valorização</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>SKU</TableHead>
                    <TableHead>Produto</TableHead>
                    <TableHead>Setor Responsável</TableHead>
                    <TableHead className="text-right">Saldo</TableHead>
                    <TableHead className="text-right">Custo Unit.</TableHead>
                    <TableHead className="text-right">Subtotal</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {valuationData.items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-mono">{item.produtos?.sku}</TableCell>
                      <TableCell>{item.produtos?.nome}</TableCell>
                      <TableCell>{item.produtos?.setor_responsavel_nome || '-'}</TableCell>
                      <TableCell className="text-right">{item.saldo_atual}</TableCell>
                      <TableCell className="text-right">{formatCurrency(item.preco_custo)}</TableCell>
                      <TableCell className="text-right font-medium">{formatCurrency(item.valor_total)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default EstoqueRelatoriosPage;
