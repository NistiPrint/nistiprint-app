import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import ProductSelector from '@/components/ui/ProductSelector';
import ProductDisplay from '@/components/ui/ProductDisplay';
import { estoqueService } from '@/services/EstoqueService';
import { Package, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

function EstoquePosicaoPage() {
  const [posicaoEstoque, setPosicaoEstoque] = useState([]);
  const [depositos, setDepositos] = useState([]);
  const [produtosDisponiveis, setProdutosDisponiveis] = useState([]); // All products for filter dropdown
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const filtroProdutoId = searchParams.get('produto_id') || 'all';
  const filtroDepositoId = searchParams.get('deposito_id') || 'all';

  useEffect(() => {
    const fetchPosicaoEstoque = async () => {
      setLoading(true);
      setError(null);
      try {
        const filters = {};
        if (filtroProdutoId !== 'all') filters.produto_id = filtroProdutoId;
        if (filtroDepositoId !== 'all') filters.deposito_id = filtroDepositoId;

        const data = await estoqueService.getPosicaoEstoque(filters);
        setPosicaoEstoque(data.posicao_estoque || []);
        setDepositos(data.depositos || []);
        setProdutosDisponiveis(data.produtos || []);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };

    fetchPosicaoEstoque();
  }, [filtroProdutoId, filtroDepositoId]);

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

  if (loading) return <div className="text-center py-4">Carregando Posição de Estoque...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro ao carregar posição de estoque: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-6">Posição de Estoque</h1>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Filtros</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Produto</label>
                <ProductSelector
                  value={filtroProdutoId !== 'all' ? filtroProdutoId : ''}
                  onChange={(value) => handleFilterChange('produto_id', value || 'all')}
                  placeholder="Buscar e filtrar produto..."
                />
              </div>
            </div>
            <div>
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
            </div>
            <div className="flex items-end gap-2">
              <Button onClick={handleClearFilters} variant="outline" className="w-full">
                <Search className="h-4 w-4 mr-2" /> Limpar Filtros
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-5 w-5" /> Detalhes da Posição
          </CardTitle>
        </CardHeader>
        <CardContent>
          {posicaoEstoque.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhuma posição de estoque encontrada com os filtros aplicados.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Produto</TableHead>
                  <TableHead>Setor Responsável</TableHead>
                  <TableHead>Depósito</TableHead>
                  <TableHead className="text-right">Quantidade</TableHead>
                  <TableHead className="text-right">Reservado</TableHead>
                  <TableHead className="text-right">Disponível</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {posicaoEstoque.map((item, index) => (
                  <TableRow key={index}>
                    <TableCell>
                      <ProductDisplay
                        product={
                          produtosDisponiveis.find(p => p.id === item.produto_id) ||
                          (item.produtos ? item.produtos : null)
                        }
                        productId={item.produto_id}
                      />
                    </TableCell>
                    <TableCell>
                      {produtosDisponiveis.find(p => p.id === item.produto_id)?.setor_responsavel_nome ||
                       (item.produtos && item.produtos.setor_responsavel_nome ? item.produtos.setor_responsavel_nome : '-') || '-'}
                    </TableCell>
                    <TableCell>
                      {depositos.find(d => d.id === item.deposito_id)?.name || item.deposito_id}
                    </TableCell>
                    <TableCell className="text-right">{item.quantidade}</TableCell>
                    <TableCell className="text-right">{item.reservado || 0}</TableCell>
                    <TableCell className="text-right">
                      {(() => {
                        const disponivel = item.disponivel || (item.quantidade - (item.reservado || 0));
                        const produto = produtosDisponiveis.find(p => p.id === item.produto_id) || (item.produtos ? item.produtos : null);
                        const nivelMinimo = produto?.nivel_minimo || item.nivel_minimo || 0;

                        let badgeClass = 'px-2 py-1 rounded-full text-xs font-medium ';

                        if (disponivel < nivelMinimo) {
                          // Vermelho: Abaixo do mínimo
                          badgeClass += 'bg-red-100 text-red-800';
                        } else if (disponivel < nivelMinimo * 2) {
                          // Amarelo: Próximo ao mínimo
                          badgeClass += 'bg-yellow-100 text-yellow-800';
                        } else {
                          // Verde: Estoque saudável
                          badgeClass += 'bg-green-100 text-green-800';
                        }

                        return (
                          <span className={badgeClass}>
                            {disponivel}
                          </span>
                        );
                      })()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default EstoquePosicaoPage;
