import React, { useState, useEffect } from 'react';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Package,
  ShoppingCart,
  TrendingUp,
  TrendingDown,
  Trash2,
  Save,
  CheckCircle,
  Filter
} from 'lucide-react';
import { toast } from 'sonner';

const MovimentacaoLotePage = () => {
  const [produtos, setProdutos] = useState([]);
  const [movimentacoes, setMovimentacoes] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [categoriaSelecionada, setCategoriaSelecionada] = useState('');
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);

  // Carregar informações do usuário e categorias
  useEffect(() => {
    const fetchUserInfoAndCategories = async () => {
      try {
        // Primeiro, obter informações do usuário para verificar se é admin
        const userInfoResponse = await fetch('/api/v2/current-user');
        const userInfo = await userInfoResponse.json();

        if (userInfoResponse.ok) {
          setIsAdmin(userInfo.usuario?.is_admin || false);
        }

        // Carregar categorias
        const categoriasResponse = await fetch('/api/v2/cadastros/categoria');
        const categoriasData = await categoriasResponse.json();

        if (categoriasResponse.ok) {
          setCategorias(categoriasData.categorias || []);
        }

        // Carregar produtos com base nas permissões do usuário
        let apiUrl = '/api/v2/produtos/por-setor';
        if (isAdmin) {
          apiUrl = '/api/v2/produtos?page=1&per_page=10000'; // Carregar todos os produtos para admin
        }

        const response = await fetch(apiUrl);
        const data = await response.json();

        if (response.ok) {
          let produtosComSaldo = data.produtos || data.items || [];

          // Para administradores, obter saldos de estoque para todos os produtos
          if (isAdmin && produtosComSaldo.length > 0) {
            const produtoIds = produtosComSaldo.map(p => p.id);
            try {
              const saldosResponse = await fetch('/api/v2/estoque/saldos-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ produtos: produtoIds })
              });

              if (saldosResponse.ok) {
                const saldosData = await saldosResponse.json();

                // Associar saldos aos produtos
                produtosComSaldo = produtosComSaldo.map(produto => ({
                  ...produto,
                  saldo_atual: saldosData.saldos?.[produto.id]?.quantidade || 0
                }));
              }
            } catch (saldoError) {
              console.error('Erro ao carregar saldos:', saldoError);
              // Continuar sem saldos se houver erro
              produtosComSaldo = produtosComSaldo.map(produto => ({
                ...produto,
                saldo_atual: 0
              }));
            }
          }

          setProdutos(produtosComSaldo);
        } else {
          toast.error('Erro ao carregar produtos: ' + (data.error || 'Ocorreu um erro desconhecido'));
        }
      } catch (error) {
        toast.error('Não foi possível conectar ao servidor');
      } finally {
        setLoading(false);
      }
    };

    fetchUserInfoAndCategories();
  }, []);

  // Função para adicionar movimentação
  const adicionarMovimentacao = (produtoId, tipo) => {
    const produto = produtos.find(p => p.id === produtoId);
    if (!produto) return;

    const quantidadeInput = document.getElementById(`quantidade-${produtoId}`);
    if (!quantidadeInput) return;
    
    const quantidade = parseFloat(quantidadeInput.value);
    if (!quantidade || quantidade <= 0) {
      toast.warning('Quantidade inválida: Por favor, informe uma quantidade válida');
      return;
    }

    // Verificar se já existe uma movimentação pendente para este produto
    const indexExistente = movimentacoes.findIndex(m => m.produto_id === produtoId);

    if (indexExistente >= 0) {
      // Atualizar movimentação existente
      const novasMovimentacoes = [...movimentacoes];
      novasMovimentacoes[indexExistente] = {
        ...novasMovimentacoes[indexExistente],
        quantidade,
        tipo_movimento: tipo
      };
      setMovimentacoes(novasMovimentacoes);
    } else {
      // Adicionar nova movimentação
      const novaMovimentacao = {
        produto_id: produtoId,
        quantidade,
        tipo_movimento: tipo,
        nome_produto: produto.nome,
        sku: produto.sku
      };
      setMovimentacoes([...movimentacoes, novaMovimentacao]);
    }

    // Limpar campo de quantidade
    quantidadeInput.value = '';

    toast.success(`Produto ${produto.nome} adicionado à lista de movimentação`);
  };

  // Função para remover movimentação
  const removerMovimentacao = (produtoId) => {
    setMovimentacoes(movimentacoes.filter(m => m.produto_id !== produtoId));
  };

  // Função para salvar movimentações em lote
  const salvarMovimentacoes = async () => {
    if (movimentacoes.length === 0) {
      toast.warning('Nenhuma movimentação: Adicione pelo menos uma movimentação para salvar');
      return;
    }

    try {
      const response = await fetch('/api/v2/estoque/movimentar-lote', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ movimentacoes }),
      });

      const data = await response.json();

      if (response.ok) {
        toast.success(`Movimentações salvas com sucesso: ${data.sucesso} movimentações realizadas com sucesso. ${data.falhas} falhas ocorreram.`);
        // Limpar lista de movimentações após salvar
        setMovimentacoes([]);
      } else {
        toast.error('Erro ao salvar movimentações: ' + (data.error || 'Ocorreu um erro desconhecido'));
      }
    } catch (error) {
      toast.error('Não foi possível conectar ao servidor');
    }
  };

  // Função para filtrar produtos por categoria
  const produtosFiltrados = categoriaSelecionada
    ? produtos.filter(produto => produto.categoria_id === parseInt(categoriaSelecionada))
    : produtos;

  return (
    <div className="movimentacao-lote-page space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package size={24} />
            Movimentação de Estoque em Lote
          </CardTitle>
          <CardDescription>
            {isAdmin
              ? 'Selecione produtos e registre entradas ou saídas em lote. Você pode filtrar por categoria.'
              : 'Selecione produtos do seu setor e registre entradas ou saídas em lote.'}
          </CardDescription>
        </CardHeader>
      </Card>

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Filter size={18} />
              Filtro por Categoria
            </CardTitle>
            <CardDescription>
              Selecione uma categoria para reduzir a lista de produtos disponíveis para movimentação
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="categoria-select" className="block text-sm font-medium mb-2">
                  Categoria
                </label>
                <Select value={categoriaSelecionada} onValueChange={setCategoriaSelecionada}>
                  <SelectTrigger id="categoria-select" className="w-full">
                    <SelectValue placeholder="Selecione uma categoria (opcional)" />
                  </SelectTrigger>
                  <SelectContent>
                    {categorias.map((categoria) => (
                      <SelectItem key={categoria.id} value={categoria.id.toString()}>
                        {categoria.nome}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  variant="outline"
                  onClick={() => setCategoriaSelecionada('')}
                  disabled={!categoriaSelecionada}
                >
                  Limpar Filtro
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShoppingCart size={18} />
            {isAdmin ? 'Todos os Produtos' : 'Produtos do Setor'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Nome</TableHead>
                  <TableHead>Categoria</TableHead>
                  <TableHead>Saldo Atual</TableHead>
                  <TableHead>Quantidade</TableHead>
                  <TableHead>Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center">
                      Carregando produtos...
                    </TableCell>
                  </TableRow>
                ) : produtosFiltrados.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center">
                      {categoriaSelecionada
                        ? 'Nenhum produto encontrado para a categoria selecionada'
                        : isAdmin
                          ? 'Nenhum produto encontrado'
                          : 'Nenhum produto encontrado para o seu setor'}
                    </TableCell>
                  </TableRow>
                ) : (
                  produtosFiltrados.map((produto) => (
                    <TableRow key={produto.id}>
                      <TableCell>{produto.sku}</TableCell>
                      <TableCell>{produto.nome}</TableCell>
                      <TableCell>{produto.categoria_nome || produto.categoria_id || '-'}</TableCell>
                      <TableCell>{produto.saldo_atual || 0}</TableCell>
                      <TableCell>
                        <Input
                          id={`quantidade-${produto.id}`}
                          type="number"
                          min="1"
                          placeholder="Quantidade"
                          className="w-32"
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => adicionarMovimentacao(produto.id, 'ENTRADA')}
                            title="Registrar Entrada"
                          >
                            <TrendingUp size={16} className="mr-1" />
                            Entrada
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => adicionarMovimentacao(produto.id, 'SAIDA')}
                            title="Registrar Saída"
                          >
                            <TrendingDown size={16} className="mr-1" />
                            Saída
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp size={18} />
            Movimentações Pendentes
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Nome</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Quantidade</TableHead>
                  <TableHead>Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {movimentacoes.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-gray-500">
                      Nenhuma movimentação pendente
                    </TableCell>
                  </TableRow>
                ) : (
                  movimentacoes.map((mov) => (
                    <TableRow key={mov.produto_id}>
                      <TableCell>{mov.sku}</TableCell>
                      <TableCell>{mov.nome_produto}</TableCell>
                      <TableCell>
                        <Badge variant={mov.tipo_movimento === 'ENTRADA' ? 'default' : 'destructive'}>
                          {mov.tipo_movimento === 'ENTRADA' ? 'Entrada' : 'Saída'}
                        </Badge>
                      </TableCell>
                      <TableCell>{mov.quantidade}</TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => removerMovimentacao(mov.produto_id)}
                        >
                          <Trash2 size={16} className="mr-1" />
                          Remover
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
          
          <div className="flex justify-end mt-6">
            <Button
              size="lg"
              disabled={movimentacoes.length === 0}
              onClick={salvarMovimentacoes}
            >
              <Save size={16} className="mr-2" />
              Salvar Todas as Movimentações
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default MovimentacaoLotePage;
