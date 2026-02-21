import { ProductLevelBadge } from '@/components/produtos/ProductLevelBadge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Copy, Edit, PlusCircle, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import CategoryService from '../../services/CategoryService';
import ProductService from '../../services/ProductService';
import SectorService from '../../services/SectorService';

function ProdutoListPage() {
  const [produtos, setProdutos] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [setores, setSetores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const [totalPages, setTotalPages] = useState(1);

  // Bulk Selection State
  const [selectedProductIds, setSelectedProductIds] = useState([]);
  const [bulkUpdateDialogOpen, setBulkUpdateDialogOpen] = useState(false);
  const [selectedBulkMaterialType, setSelectedBulkMaterialType] = useState('');
  const [bulkUpdateCategoryDialogOpen, setBulkUpdateCategoryDialogOpen] = useState(false);
  const [selectedBulkCategoryId, setSelectedBulkCategoryId] = useState('none');
  const [bulkUpdateLoading, setBulkUpdateLoading] = useState(false);

  // Bulk Update Setor State
  const [bulkUpdateSetorDialogOpen, setBulkUpdateSetorDialogOpen] = useState(false);
  const [selectedBulkSetorId, setSelectedBulkSetorId] = useState('');

  // Delete Dialog State
  const [singleDeleteDialogOpen, setSingleDeleteDialogOpen] = useState(false);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);
  const [productToDelete, setProductToDelete] = useState(null);

  const currentPage = parseInt(searchParams.get('page')) || 1;
  const searchTerm = searchParams.get('q') || '';
  const categoryFilter = searchParams.get('category_id') || 'all';
  const statusFilter = searchParams.get('status') || 'all';
  const materialTypeFilter = searchParams.get('material_type') || 'all';

  // Local search input state
  const [searchInput, setSearchInput] = useState(searchTerm);

  useEffect(() => {
    loadAuxiliaryData();
  }, []);

  useEffect(() => {
    fetchProdutos();
  }, [currentPage, searchTerm, categoryFilter, statusFilter, materialTypeFilter]);

  // Sincroniza o input local se o searchTerm mudar (ex: navegação)
  useEffect(() => {
    setSearchInput(searchTerm);
  }, [searchTerm]);

  const loadAuxiliaryData = async () => {
    try {
      const [categoriasData, setoresData] = await Promise.all([
        CategoryService.getAll(),
        SectorService.getAll()
      ]);
      setCategorias(categoriasData || []);
      setSetores(setoresData || []);
    } catch (error) {
      console.error("Failed to load auxiliary data", error);
    }
  };

  const fetchProdutos = async () => {
    setLoading(true);
    setSelectedProductIds([]); // Clear selection on new fetch
    try {
      const params = {
        page: currentPage,
        q: searchTerm,
        category_id: categoryFilter === 'all' ? '' : categoryFilter,
        status: statusFilter === 'all' ? '' : statusFilter,
        material_type: materialTypeFilter === 'all' ? '' : materialTypeFilter,
        setor_id: searchParams.get('setor_id') === 'all' ? '' :
                 searchParams.get('setor_id') === 'none' ? 'null' : searchParams.get('setor_id'),
      };

      const data = await ProductService.getAll(params);
      setProdutos(data.produtos || []);
      setTotalPages(data.total_pages || 1);
    } catch (e) {
      toast.error("Erro ao carregar produtos: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    setSearchParams(prev => {
      const newParams = new URLSearchParams(prev);
      if (searchInput) {
        newParams.set('q', searchInput);
      } else {
        newParams.delete('q');
      }
      newParams.set('page', '1');
      return newParams;
    }, { replace: true });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const handleFilterChange = (key, value) => {
    setSearchParams(prev => {
      const newParams = new URLSearchParams(prev);
      if (value && value !== 'all') {
        newParams.set(key, value);
      } else {
        newParams.delete(key);
      }
      newParams.set('page', '1');
      return newParams;
    }, { replace: true });
  };

  const handlePageChange = (newPage) => {
    setSearchParams(prev => {
      prev.set('page', newPage);
      return prev;
    }, { replace: true });
  };

  const confirmDelete = (produto) => {
    setProductToDelete(produto);
    setSingleDeleteDialogOpen(true);
  };

  const handleDelete = async () => {
    if (!productToDelete) return;

    try {
      await ProductService.delete(productToDelete.id);
      toast.success("Produto excluído com sucesso!");
      fetchProdutos(); // Refresh list
    } catch (error) {
      toast.error(`Erro ao excluir: ${error.response?.data?.error || error.message}`);
    } finally {
      setSingleDeleteDialogOpen(false);
      setProductToDelete(null);
    }
  };

  const handleSelectAll = (checked) => {
    if (checked) {
      const allProductIds = produtos.map(produto => produto.id);
      setSelectedProductIds(allProductIds);
    } else {
      setSelectedProductIds([]);
    }
  };

  const handleSelectProduct = (productId) => {
    setSelectedProductIds(prev =>
      prev.includes(productId)
        ? prev.filter(id => id !== productId)
        : [...prev, productId]
    );
  };

  const handleBulkUpdateMaterialType = async () => {
    if (selectedProductIds.length === 0) {
      toast.error("Nenhum produto selecionado para atualização.");
      return;
    }
    if (!selectedBulkMaterialType) {
      toast.error("Por favor, selecione um tipo de material.");
      return;
    }

    setBulkUpdateLoading(true);
    try {
      const response = await ProductService.bulkUpdate(selectedProductIds, {
        material_type: selectedBulkMaterialType,
      });
      toast.success(response.message || "Produtos atualizados com sucesso!");
      setBulkUpdateDialogOpen(false);
      setSelectedBulkMaterialType('');
      fetchProdutos(); // Re-fetch products to show updated values
    } catch (error) {
      toast.error(`Erro ao atualizar produtos: ${error.message}`);
    } finally {
      setBulkUpdateLoading(false);
    }
  };

  const handleBulkUpdateCategory = async () => {
    if (selectedProductIds.length === 0) {
      toast.error("Nenhum produto selecionado para atualização.");
      return;
    }
    if (!selectedBulkCategoryId) {
      toast.error("Por favor, selecione uma categoria.");
      return;
    }

    setBulkUpdateLoading(true);
    try {
      const response = await ProductService.bulkUpdate(selectedProductIds, {
        category_id: selectedBulkCategoryId === 'none' ? null : selectedBulkCategoryId,
      });
      toast.success(response.message || "Produtos atualizados com sucesso!");
      setBulkUpdateCategoryDialogOpen(false);
      setSelectedBulkCategoryId('');
      fetchProdutos(); // Re-fetch products to show updated values
    } catch (error) {
      toast.error(`Erro ao atualizar produtos: ${error.message}`);
    } finally {
      setBulkUpdateLoading(false);
    }
  };

  const handleBulkUpdateSetor = async () => {
    if (selectedProductIds.length === 0) {
      toast.error("Nenhum produto selecionado para atualização.");
      return;
    }

    setBulkUpdateLoading(true);
    try {
      const response = await ProductService.bulkUpdate(selectedProductIds, {
        setor_responsavel_id: selectedBulkSetorId === 'none' ? null : selectedBulkSetorId,
      });
      toast.success(response.message || "Produtos atualizados com sucesso!");
      setBulkUpdateSetorDialogOpen(false);
      setSelectedBulkSetorId('');
      fetchProdutos(); // Re-fetch products to show updated values
    } catch (error) {
      toast.error(`Erro ao atualizar produtos: ${error.message}`);
    } finally {
      setBulkUpdateLoading(false);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedProductIds.length === 0) {
      toast.error("Nenhum produto selecionado para exclusão.");
      return;
    }

    setBulkUpdateLoading(true);
    try {
      // Loop through each selected product ID and delete it
      const promises = selectedProductIds.map(productId => ProductService.delete(productId));
      await Promise.all(promises);

      toast.success(`${selectedProductIds.length} produto(s) excluído(s) com sucesso!`);
      setBulkDeleteDialogOpen(false);
      setSelectedProductIds([]); // Clear selection
      fetchProdutos(); // Re-fetch products to update the list
    } catch (error) {
      toast.error(`Erro ao excluir produtos: ${error.response?.data?.error || error.message}`);
    } finally {
      setBulkUpdateLoading(false);
    }
  };


  return (
    <Card>
      <CardHeader className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-6">
        <div>
          <CardTitle className="text-2xl font-bold flex items-center gap-2">
            📦 Catálogo de Produtos
          </CardTitle>
          <p className="text-sm text-muted-foreground mt-1">Gerencie seus produtos, composições e integrações.</p>
        </div>
        <div className="flex items-center gap-2">
           {/* Future feature: Update costs */}
          {/* <Button variant="outline" size="sm" className="hidden md:flex">
            <RefreshCw className="h-4 w-4 mr-2" /> Atualizar Custos
          </Button> */}
          <Link to="/produtos/novo">
            <Button>
              <PlusCircle className="h-4 w-4 mr-2" /> Novo Produto
            </Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent>
        {/* Filters Toolbar */}
        <div className="flex flex-col md:flex-row gap-3 mb-6">
          <div className="flex-1 flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Buscar por SKU ou nome..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={handleKeyDown}
                className="pl-8"
              />
            </div>
            <Button onClick={handleSearch} variant="secondary">
              <Search className="h-4 w-4 mr-2" />
              Pesquisar
            </Button>
          </div>
          <div className="w-full md:w-[200px]">
            <Select 
              value={categoryFilter} 
              onValueChange={(val) => handleFilterChange('category_id', val)}
            >
              <SelectTrigger className="bg-white">
                <SelectValue placeholder="Categoria" />
              </SelectTrigger>
              <SelectContent className="bg-white">
                <SelectItem value="all">Todas as Categorias</SelectItem>
                {categorias.map(cat => (
                  <SelectItem key={cat.id} value={String(cat.id)}>{cat.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-full md:w-[200px]">
            <Select 
              value={materialTypeFilter} 
              onValueChange={(val) => handleFilterChange('material_type', val)}
            >
              <SelectTrigger className="bg-white">
                <SelectValue placeholder="Nível do Produto" />
              </SelectTrigger>
              <SelectContent className="bg-white">
                <SelectItem value="all">Todos os Níveis</SelectItem>
                <SelectItem value="materia_prima">Matéria Prima</SelectItem>
                <SelectItem value="intermediario">Intermediário</SelectItem>
                <SelectItem value="produto_acabado">Produto Acabado</SelectItem>
                <SelectItem value="servico">Serviço</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-full md:w-[200px]">
            <Select
              value={statusFilter}
              onValueChange={(val) => handleFilterChange('status', val)}
            >
              <SelectTrigger className="bg-white">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent className="bg-white">
                <SelectItem value="all">Todos Status</SelectItem>
                <SelectItem value="ativo">Ativo</SelectItem>
                <SelectItem value="rascunho">Rascunho</SelectItem>
                <SelectItem value="inativo">Inativo</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="w-full md:w-[200px]">
            <Select
              value={searchParams.get('setor_id') || 'all'}
              onValueChange={(val) => handleFilterChange('setor_id', val)}
            >
              <SelectTrigger className="bg-white">
                <SelectValue placeholder="Setor" />
              </SelectTrigger>
              <SelectContent className="bg-white">
                <SelectItem value="all">Todos os Setores</SelectItem>
                <SelectItem value="none">Sem Setor</SelectItem>
                {setores.map(setor => (
                  <SelectItem key={setor.id} value={String(setor.id)}>{setor.nome}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Bulk Actions Toolbar */}
        {selectedProductIds.length > 0 && (
            <div className="flex items-center gap-3 p-3 mb-4 bg-primary/10 rounded-md border border-primary text-primary-foreground">
                <span className="text-sm font-medium">{selectedProductIds.length} produto(s) selecionado(s)</span>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setBulkUpdateDialogOpen(true)}
                    className="bg-white text-primary hover:bg-primary-foreground"
                >
                    Alterar Nível do Produto
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setBulkUpdateCategoryDialogOpen(true)}
                    className="bg-white text-primary hover:bg-primary-foreground"
                >
                    Alterar Categoria
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setBulkUpdateSetorDialogOpen(true)}
                    className="bg-white text-primary hover:bg-primary-foreground"
                >
                    Alterar Setor
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setBulkDeleteDialogOpen(true)}
                    className="bg-red-50 text-red-600 hover:bg-red-100"
                >
                    Excluir Selecionados
                </Button>
            </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <RefreshCw className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : produtos.length === 0 ? (
          <div className="text-center py-12 border rounded-md bg-muted/10">
            <p className="text-lg font-semibold">Nenhum produto encontrado.</p>
            <p className="text-muted-foreground">Tente ajustar os filtros ou crie um novo produto.</p>
          </div>
        ) : (
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[40px] text-center">
                    <Checkbox
                        checked={selectedProductIds.length === produtos.length && produtos.length > 0}
                        onCheckedChange={handleSelectAll}
                    />
                  </TableHead>
                  <TableHead>Nome do Produto</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>Nível</TableHead>
                  <TableHead>Setor Responsável</TableHead>
                  <TableHead>Preço de Venda</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {produtos.map((produto) => (
                  <TableRow key={produto.id}>
                    <TableCell className="text-center">
                      <Checkbox
                        checked={selectedProductIds.includes(produto.id)}
                        onCheckedChange={() => handleSelectProduct(produto.id)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="font-medium flex items-center gap-2">
                        {produto.name}
                        {produto.has_variants && (
                          <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full">
                            {produto.variants?.length || 0} variações
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{produto.sku_mestre || '-'}</TableCell>
                    <TableCell>
                       <ProductLevelBadge type={produto.material_type} />
                    </TableCell>
                    <TableCell>
                      {produto.setor_responsavel_nome || '-'}
                    </TableCell>
                    <TableCell>R$ {produto.price ? parseFloat(produto.price).toFixed(2) : '0.00'}</TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        produto.status === 'ativo' ? 'bg-green-100 text-green-800' :
                        produto.status === 'rascunho' ? 'bg-yellow-100 text-yellow-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {produto.status || 'ativo'}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {produto.parent_id ? (
                          <Link to={`/produtos/${produto.parent_id}/editar?variation_id=${produto.id}`}>
                            <Button variant="ghost" size="icon" title="Editar Variação">
                              <Edit className="h-4 w-4 text-blue-600" />
                            </Button>
                          </Link>
                        ) : (
                          <Link to={`/produtos/${produto.id}/editar`}>
                            <Button variant="ghost" size="icon" title="Editar Produto">
                              <Edit className="h-4 w-4 text-blue-600" />
                            </Button>
                          </Link>
                        )}
                        <Link to={`/produtos/novo?clone_id=${produto.id}`}>
                          <Button variant="ghost" size="icon" title="Clonar Produto">
                            <Copy className="h-4 w-4 text-green-600" />
                          </Button>
                        </Link>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => confirmDelete(produto)}
                        >
                          <Trash2 className="h-4 w-4 text-red-600" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* Pagination */}
        <div className="flex items-center justify-between py-4">
          <div className="text-sm text-muted-foreground">
            Página {currentPage} de {totalPages}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              Anterior
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage >= totalPages}
            >
              Próxima
            </Button>
          </div>
        </div>
      </CardContent>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={singleDeleteDialogOpen} onOpenChange={setSingleDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Tem certeza absoluta?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta ação não pode ser desfeita. Isso excluirá permanentemente o produto
              <strong> {productToDelete?.name}</strong> e removerá seus dados.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-700">
              Sim, excluir
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Update Material Type Dialog */}
      <AlertDialog open={bulkUpdateDialogOpen} onOpenChange={setBulkUpdateDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Alterar Nível do Produto em Massa</AlertDialogTitle>
            <AlertDialogDescription>
              Você está prestes a alterar o nível para <strong>{selectedProductIds.length}</strong> produto(s) selecionado(s).
              Selecione o novo nível abaixo:
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-4 py-4">
            <Select onValueChange={setSelectedBulkMaterialType} value={selectedBulkMaterialType}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Selecione o novo nível" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="produto_acabado">Produto Acabado</SelectItem>
                <SelectItem value="materia_prima">Matéria Prima</SelectItem>
                <SelectItem value="intermediario">Intermediário</SelectItem>
                <SelectItem value="servico">Serviço</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={bulkUpdateLoading}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleBulkUpdateMaterialType} disabled={bulkUpdateLoading || !selectedBulkMaterialType}>
              {bulkUpdateLoading && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Confirmar Alteração
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Update Category Dialog */}
      <AlertDialog open={bulkUpdateCategoryDialogOpen} onOpenChange={setBulkUpdateCategoryDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Alterar Categoria em Massa</AlertDialogTitle>
            <AlertDialogDescription>
              Você está prestes a alterar a categoria para <strong>{selectedProductIds.length}</strong> produto(s) selecionado(s).
              Selecione a nova categoria abaixo:
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-4 py-4">
            <Select onValueChange={setSelectedBulkCategoryId} value={selectedBulkCategoryId}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Selecione a nova categoria" />
              </SelectTrigger>
              <SelectContent className="max-h-60 overflow-y-auto">
                <SelectItem value="none">Nenhuma</SelectItem>
                {categorias.map(cat => (
                  <SelectItem key={cat.id} value={String(cat.id)}>{cat.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={bulkUpdateLoading}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleBulkUpdateCategory} disabled={bulkUpdateLoading || !selectedBulkCategoryId}>
              {bulkUpdateLoading && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Confirmar Alteração
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Update Setor Dialog */}
      <AlertDialog open={bulkUpdateSetorDialogOpen} onOpenChange={setBulkUpdateSetorDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Alterar Setor em Massa</AlertDialogTitle>
            <AlertDialogDescription>
              Você está prestes a alterar o setor responsável para <strong>{selectedProductIds.length}</strong> produto(s) selecionado(s).
              Selecione o novo setor abaixo:
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-4 py-4">
            <Select onValueChange={setSelectedBulkSetorId} value={selectedBulkSetorId}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Selecione o novo setor" />
              </SelectTrigger>
              <SelectContent className="max-h-60 overflow-y-auto">
                <SelectItem value="none">Nenhum Setor</SelectItem>
                {setores.map(setor => (
                  <SelectItem key={setor.id} value={String(setor.id)}>{setor.nome}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={bulkUpdateLoading}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleBulkUpdateSetor} disabled={bulkUpdateLoading || !selectedBulkSetorId}>
              {bulkUpdateLoading && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Confirmar Alteração
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Delete Dialog */}
      <AlertDialog open={bulkDeleteDialogOpen && selectedProductIds.length > 0} onOpenChange={setBulkDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Tem certeza absoluta?</AlertDialogTitle>
            <AlertDialogDescription>
              Esta ação não pode ser desfeita. Isso excluirá permanentemente <strong>{selectedProductIds.length}</strong> produto(s) selecionado(s)
              e removerá todos os seus dados.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={handleBulkDelete} className="bg-red-600 hover:bg-red-700">
              Sim, excluir
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

export default ProdutoListPage;
