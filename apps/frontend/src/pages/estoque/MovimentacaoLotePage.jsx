import React, { useState, useEffect, useRef } from 'react';
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
import { createOperationId } from '@/lib/operationId';

const PENDING_BATCH_STORAGE_KEY = 'nistiprint:estoque:movimentacao-lote:pending:v1';

const readPendingBatch = () => {
  try {
    const pending = JSON.parse(sessionStorage.getItem(PENDING_BATCH_STORAGE_KEY) || 'null');
    if (
      pending &&
      typeof pending.operation_id === 'string' &&
      Array.isArray(pending.movimentacoes) &&
      pending.movimentacoes.length > 0
    ) return pending;
  } catch {
    // A session storage ausente/corrompida não deve impedir o uso da página.
  }
  return null;
};

const MovimentacaoLotePage = () => {
  const [produtos, setProdutos] = useState([]);
  const [pendingCommand, setPendingCommand] = useState(readPendingBatch);
  const [movimentacoes, setMovimentacoes] = useState(() => readPendingBatch()?.movimentacoes || []);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [loadError, setLoadError] = useState('');
  const [categorias, setCategorias] = useState([]);
  const [categoriaSelecionada, setCategoriaSelecionada] = useState('');
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [identityReady, setIdentityReady] = useState(false);
  const [produtoPage, setProdutoPage] = useState(1);
  const [produtoTotalPages, setProdutoTotalPages] = useState(1);

  // Carregar informações do usuário e categorias
  useEffect(() => {
    let active = true;
    const fetchUserInfoAndCategories = async () => {
      try {
        setLoadError('');
        // Primeiro, obter informações do usuário para verificar se é admin
        const userInfoResponse = await fetch('/api/v2/current-user');
        if (!userInfoResponse.ok) throw new Error('Não foi possível confirmar a sessão do usuário.');
        const userInfo = await userInfoResponse.json();
        const adminUser = userInfoResponse.ok && Boolean(userInfo.usuario?.is_admin);
        if (!active) return;
        setIsAdmin(adminUser);

        // Carregar categorias
        const categoriasResponse = await fetch('/api/v2/cadastros/categoria');
        const categoriasData = await categoriasResponse.json();

        if (active && categoriasResponse.ok) {
          setCategorias(categoriasData.categorias || []);
        }
        if (active) setIdentityReady(true);
      } catch (error) {
        const message = error.message || 'Não foi possível conectar ao servidor.';
        if (active) {
          setLoadError(message);
          setLoading(false);
          toast.error(message);
        }
      }
    };

    fetchUserInfoAndCategories();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!identityReady) return undefined;
    let active = true;
    const fetchProductPage = async () => {
      setLoading(true);
      setLoadError('');
      try {
        const params = new URLSearchParams({ page: String(produtoPage), per_page: '100' });
        if (categoriaSelecionada) params.set('category_id', categoriaSelecionada);
        const endpoint = isAdmin ? '/api/v2/produtos' : '/api/v2/produtos/por-setor';
        const response = await fetch(`${endpoint}?${params.toString()}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Não foi possível carregar esta página de produtos.');

        let pageProducts = data.produtos || data.items || [];
        if (!Array.isArray(pageProducts)) throw new Error('A resposta de produtos está inválida.');
        if (isAdmin && pageProducts.length > 0) {
          const saldoResponse = await fetch('/api/v2/estoque/saldos-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_ids: pageProducts.map((product) => product.id) }),
          });
          const saldoData = await saldoResponse.json();
          if (!saldoResponse.ok) throw new Error(saldoData.error || 'Não foi possível confirmar os saldos do depósito.');
          pageProducts = pageProducts.map((product) => {
            const balance = saldoData[String(product.id)];
            if (!balance || balance.quantidade === undefined || balance.quantidade === null) {
              throw new Error(`Não foi possível confirmar o saldo do produto ${product.id}.`);
            }
            return { ...product, saldo_atual: balance.quantidade };
          });
        }
        if (active) {
          setProdutos(pageProducts);
          setProdutoTotalPages(Math.max(1, Number(data.total_pages) || 1));
        }
      } catch (error) {
        if (active) {
          setProdutos([]);
          setLoadError(error.message || 'Não foi possível carregar os produtos.');
          toast.error(error.message || 'Não foi possível carregar os produtos.');
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    fetchProductPage();
    return () => { active = false; };
  }, [identityReady, isAdmin, produtoPage, categoriaSelecionada]);

  // Função para adicionar movimentação
  const adicionarMovimentacao = (produtoId, tipo) => {
    if (pendingCommand) {
      toast.warning('Este lote tem resultado pendente. Repita o envio com o mesmo identificador antes de alterá-lo.');
      return;
    }
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
    if (pendingCommand) return;
    setMovimentacoes(movimentacoes.filter(m => m.produto_id !== produtoId));
  };

  // Função para salvar movimentações em lote
  const salvarMovimentacoes = async () => {
    if (savingRef.current || saving) return;
    if (movimentacoes.length === 0) {
      toast.warning('Nenhuma movimentação: Adicione pelo menos uma movimentação para salvar');
      return;
    }
    savingRef.current = true;
    setSaving(true);

    const command = pendingCommand || {
      operation_id: createOperationId(),
      movimentacoes: movimentacoes.map(({ produto_id, quantidade, tipo_movimento, deposito_id, motivo, documento_referencia }) => ({
        produto_id,
        quantidade,
        tipo_movimento,
        ...(deposito_id ? { deposito_id } : {}),
        ...(motivo ? { motivo } : {}),
        ...(documento_referencia ? { documento_referencia } : {}),
      })),
    };
    if (!pendingCommand) {
      try {
        sessionStorage.setItem(PENDING_BATCH_STORAGE_KEY, JSON.stringify(command));
      } catch {
        savingRef.current = false;
        setSaving(false);
        toast.error('Não foi possível salvar a identidade do lote nesta sessão; nenhuma movimentação foi enviada.');
        return;
      }
      setPendingCommand(command);
    }

    try {
      const response = await fetch('/api/v2/estoque/movimentar-lote', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(command),
      });

      const data = await response.json().catch(() => ({}));

      if (response.ok) {
        sessionStorage.removeItem(PENDING_BATCH_STORAGE_KEY);
        setPendingCommand(null);
        toast.success(`Lote ${data.operation_id || command.operation_id} confirmado: ${data.sucesso} movimentações aplicadas.`);
        setMovimentacoes([]);
      } else if ([400, 403, 422].includes(response.status)) {
        sessionStorage.removeItem(PENDING_BATCH_STORAGE_KEY);
        setPendingCommand(null);
        toast.error('Lote não aplicado: ' + (data.error || 'Revise os dados e tente novamente.'));
      } else {
        setPendingCommand(command);
        toast.error(`${data.error || 'Resultado do lote ainda não confirmado.'} Repita o envio para consultar/aplicar o mesmo lote.`);
      }
    } catch (error) {
      setPendingCommand(command);
      toast.error('Não foi possível confirmar o resultado. O lote foi preservado; repita o envio com a mesma identidade.');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  // A categoria já é aplicada na consulta paginada do servidor.
  const produtosFiltrados = produtos;

  return (
    <div className="movimentacao-lote-page space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package size={24} />
            Movimentação de Estoque em Lote
          </CardTitle>
          {pendingCommand && (
            <CardDescription role="status">
              Resultado pendente para {pendingCommand.operation_id}. Repita o envio para recuperar a confirmação; os itens estão bloqueados para preservar o conteúdo original.
            </CardDescription>
          )}
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
                <Select value={categoriaSelecionada} onValueChange={(value) => {
                  setCategoriaSelecionada(value);
                  setProdutoPage(1);
                }}>
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
                  onClick={() => {
                    setCategoriaSelecionada('');
                    setProdutoPage(1);
                  }}
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
                ) : loadError ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-destructive" role="alert">
                      {loadError}
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
                          disabled={Boolean(pendingCommand)}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => adicionarMovimentacao(produto.id, 'ENTRADA')}
                            title="Registrar Entrada"
                            disabled={Boolean(pendingCommand) || saving}
                          >
                            <TrendingUp size={16} className="mr-1" />
                            Entrada
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => adicionarMovimentacao(produto.id, 'SAIDA')}
                            title="Registrar Saída"
                            disabled={Boolean(pendingCommand) || saving}
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
          <div className="flex items-center justify-between mt-4">
            <Button
              variant="outline"
              disabled={loading || produtoPage <= 1}
              onClick={() => setProdutoPage((page) => Math.max(1, page - 1))}
            >
              Anterior
            </Button>
            <span className="text-sm text-muted-foreground">Página {produtoPage} de {produtoTotalPages}</span>
            <Button
              variant="outline"
              disabled={loading || produtoPage >= produtoTotalPages}
              onClick={() => setProdutoPage((page) => Math.min(produtoTotalPages, page + 1))}
            >
              Próxima
            </Button>
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
                          disabled={Boolean(pendingCommand) || saving}
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
              disabled={movimentacoes.length === 0 || saving}
              onClick={salvarMovimentacoes}
            >
              <Save size={16} className="mr-2" />
              {saving ? 'Enviando...' : pendingCommand ? 'Repetir Lote Pendente' : 'Salvar Todas as Movimentações'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default MovimentacaoLotePage;
