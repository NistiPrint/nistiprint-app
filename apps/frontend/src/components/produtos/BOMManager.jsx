import React, { useState, useEffect } from 'react';
import ProductService from '../../services/ProductService';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableFooter } from '@/components/ui/table';
import { Trash2, Plus, Search, Edit2, Save, X } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ProductLevelBadge } from '@/components/produtos/ProductLevelBadge';

const BOMManager = ({ productId, formato }) => {
  const [components, setComponents] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);

  // Search State
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [quantity, setQuantity] = useState('');
  const [searchCategoryId, setSearchCategoryId] = useState(null);

  // Edit State
  const [editingId, setEditingId] = useState(null);
  const [editQuantity, setEditQuantity] = useState('');

  // Debounce search
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if ((searchTerm.length >= 3 || (searchTerm.length === 0 && searchCategoryId)) && !selectedProduct) {
        performSearch(searchTerm, searchCategoryId);
      } else if (searchTerm.length < 3 && !searchCategoryId) {
        setSearchResults([]);
      }
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, selectedProduct, searchCategoryId]);

  useEffect(() => {
    if (productId) {
      loadBOM();
      loadRules();
    }
  }, [productId]);

  const loadBOM = async () => {
    setLoading(true);
    try {
      const data = await ProductService.getBOM(productId);
      setComponents(data.components || []); // Adjust based on actual API response
    } catch (error) {
      console.error("Error loading BOM:", error);
      // toast.error("Erro ao carregar componentes.");
    } finally {
      setLoading(false);
    }
  };

  const loadRules = async () => {
    try {
      const data = await ProductService.getCategoryRulesByProductId(productId);
      setRules(data.regras || []);
    } catch (error) {
      console.error("Error loading category rules:", error);
    }
  };

  const performSearch = async (value, categoryId = null) => {
    setIsSearching(true);
    try {
      // Determine the search context based on product format
      let contexto = null;
      if (formato === 'kit') {
        contexto = 'kit'; // For kits, allow commercializable products
      } else if (formato === 'composicao') {
        contexto = 'producao'; // For compositions, focus on raw materials
      }

      const results = await ProductService.search(value, {
        exclude_id: productId,
        category_id: categoryId,
        contexto: contexto  // Pass the context to influence search results
      });
      // Already filtered by exclude_id in backend, but keep it here for safety and filtering added components
      const filtered = (results.results || []).filter(p =>
        !components.some(c => c.component_id === p.id)
      );
      setSearchResults(filtered);
    } catch (error) {
      console.error("Error searching products:", error);
      toast.error("Erro ao pesquisar produtos.");
    } finally {
      setIsSearching(false);
    }
  };

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);
    
    // If user is typing again, deselect the previously selected product
    if (selectedProduct && value !== selectedProduct.name) {
      setSelectedProduct(null);
    }
  };

  const selectProduct = (product) => {
    setSelectedProduct(product);
    setSearchTerm(product.name);
    setSearchResults([]);
  };

  const handleAdd = async () => {
    if (!selectedProduct || !quantity || parseFloat(quantity) <= 0) {
      toast.error("Selecione um produto e informe uma quantidade válida.");
      return;
    }

    try {
      await ProductService.addBOMComponent(productId, selectedProduct.id, parseFloat(quantity));
      toast.success("Componente adicionado com sucesso!");
      setSearchTerm('');
      setSelectedProduct(null);
      setQuantity('');
      loadBOM();
    } catch (error) {
      toast.error(`Erro ao adicionar componente: ${error.message}`);
    }
  };

  const handleRemove = async (componentId) => {
    if (!confirm("Tem certeza que deseja remover este componente?")) return;

    try {
      await ProductService.removeBOMComponent(productId, componentId);
      toast.success("Componente removido.");
      loadBOM();
    } catch (error) {
      toast.error(`Erro ao remover componente: ${error.message}`);
    }
  };

  const startEdit = (component) => {
    setEditingId(component.component_id);
    setEditQuantity(component.quantity);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditQuantity('');
  };

  const saveEdit = async (componentId) => {
    if (!editQuantity || parseFloat(editQuantity) <= 0) {
      toast.error("Quantidade inválida.");
      return;
    }

    try {
      await ProductService.updateBOMComponent(productId, componentId, parseFloat(editQuantity));
      toast.success("Quantidade atualizada.");
      setEditingId(null);
      loadBOM();
    } catch (error) {
      toast.error(`Erro ao atualizar quantidade: ${error.message}`);
    }
  };

  const totalCost = components.reduce((acc, curr) => acc + (curr.quantity * curr.cost), 0);

  if (!productId) return <div className="p-4 text-center text-muted-foreground">Salve o produto para gerenciar a composição.</div>;

  return (
    <div className="space-y-6">
      {/* Guided BOM Rules Section */}
      {rules.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-blue-600 bg-blue-50 p-3 rounded-md border border-blue-100">
            <Search className="h-5 w-5" />
            <span className="text-sm font-medium">Composição guiada pelas sugestões da categoria</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {rules.map((rule) => {
              const selectedInRule = components.filter(c => String(c.categoria_id) === String(rule.categoria_componente_id));
              const totalQty = selectedInRule.reduce((sum, c) => sum + c.quantity, 0);
              const isFulfilled = totalQty >= rule.min_quantidade && totalQty <= rule.max_quantidade;

              return (
                <Card key={rule.id} className={isFulfilled ? "border-green-200 bg-green-50/10" : "border-blue-200 bg-blue-50/10"}>
                  <CardHeader className="py-3">
                    <div className="flex justify-between items-center">
                      <CardTitle className="text-sm font-bold">{rule.nome_grupo}</CardTitle>
                      <Badge variant={isFulfilled ? "outline" : "secondary"} className={isFulfilled ? "border-green-500 text-green-700" : ""}>
                        {totalQty} / {rule.max_quantidade === rule.min_quantidade ? rule.min_quantidade : `${rule.min_quantidade}-${rule.max_quantidade}`}
                      </Badge>
                    </div>
                  </CardHeader>
                <CardContent className="py-2 space-y-2">
                  <div className="text-xs text-muted-foreground mb-2">
                    Categoria permitida: <strong>{rule.categoria_componente_nome}</strong>
                  </div>
                  
                  {selectedInRule.length > 0 ? (
                    <div className="space-y-1">
                      {selectedInRule.map(comp => (
                        <div key={comp.component_id} className="flex justify-between items-center bg-background p-2 rounded border text-sm">
                          <span>{comp.name}</span>
                          <span className="font-mono font-bold">x{comp.quantity}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs italic text-muted-foreground py-2 text-center border border-dashed rounded">
                      Nenhum item selecionado
                    </div>
                  )}

                  <div className="pt-2">
                    <Button 
                      variant={searchCategoryId === rule.categoria_componente_id ? "default" : "outline"} 
                      size="sm" 
                      className="w-full text-xs"
                      onClick={() => {
                        if (searchCategoryId === rule.categoria_componente_id) {
                          setSearchCategoryId(null);
                        } else {
                          setSearchCategoryId(rule.categoria_componente_id);
                          setSearchTerm('');
                        }
                      }}
                    >
                      <Plus className="h-3 w-3 mr-1" /> 
                      {searchCategoryId === rule.categoria_componente_id ? "Limpar Filtro" : `Selecionar ${rule.nome_grupo}`}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
          </div>
        </div>
      )}

      {/* Add Component Section */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col md:flex-row gap-4 items-end">
            <div className="flex-1 relative w-full">
              <label className="text-sm font-medium mb-1 block">
                Buscar Componente (Nome ou SKU)
                {searchCategoryId && (
                  <Badge variant="secondary" className="ml-2 gap-1 px-2 py-0 h-5">
                    Filtrando por categoria
                    <X className="h-3 w-3 cursor-pointer" onClick={() => setSearchCategoryId(null)} />
                  </Badge>
                )}
              </label>
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input 
                  placeholder="Digite para buscar..." 
                  value={searchTerm} 
                  onChange={handleSearchChange}
                  className="pl-8"
                />
                {isSearching && (
                  <div className="absolute right-2 top-2.5">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
                  </div>
                )}
              </div>
              {searchTerm.length >= 3 && !selectedProduct && !isSearching && searchResults.length === 0 && (
                <div className="absolute z-10 w-full bg-popover border rounded-md shadow-md mt-1 p-3 text-sm text-muted-foreground">
                  Nenhum produto encontrado.
                </div>
              )}
              {searchResults.length > 0 && (
                <div className="absolute z-10 w-full bg-popover border rounded-md shadow-md mt-1 max-h-60 overflow-auto">
                  {searchResults.map(product => (
                    <div 
                      key={product.id} 
                      className="p-2 hover:bg-accent cursor-pointer text-sm"
                      onClick={() => selectProduct(product)}
                    >
                      <div className="font-medium">{product.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {product.sku} - R$ {product.cost}
                        {product.material_type && (
                          <span className="ml-2">
                            <ProductLevelBadge type={product.material_type} />
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="w-full md:w-32">
              <label className="text-sm font-medium mb-1 block">Quantidade</label>
              <Input 
                type="number" 
                step="0.0001" 
                min="0"
                placeholder="Qtd"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            <Button onClick={handleAdd} disabled={!selectedProduct}>
              <Plus className="h-4 w-4 mr-2" /> Adicionar
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Components List */}
      <div className="border rounded-md">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>SKU</TableHead>
              <TableHead>Componente</TableHead>
              <TableHead className="text-right">Custo Unit.</TableHead>
              <TableHead className="text-center">Qtd</TableHead>
              <TableHead className="text-right">Subtotal</TableHead>
              <TableHead className="text-right">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {components.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-6 text-muted-foreground">
                  Nenhum componente adicionado.
                </TableCell>
              </TableRow>
            ) : (
              components.map(comp => (
                <TableRow key={comp.component_id}>
                  <TableCell>{comp.sku}</TableCell>
                  <TableCell>
                    <div>{comp.name}</div>
                    {comp.material_type && (
                      <ProductLevelBadge type={comp.material_type} />
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    R$ {comp.cost?.toFixed(4)}
                  </TableCell>
                  <TableCell className="text-center">
                    {editingId === comp.component_id ? (
                      <div className="flex items-center justify-center gap-2">
                        <Input 
                          type="number" 
                          className="w-20 h-8 text-center" 
                          value={editQuantity}
                          onChange={(e) => setEditQuantity(e.target.value)}
                        />
                      </div>
                    ) : (
                      comp.quantity
                    )}
                  </TableCell>
                  <TableCell className="text-right font-medium">
                    R$ {(comp.quantity * comp.cost).toFixed(4)}
                  </TableCell>
                  <TableCell className="text-right">
                    {editingId === comp.component_id ? (
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="icon" onClick={() => saveEdit(comp.component_id)}>
                          <Save className="h-4 w-4 text-green-600" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={cancelEdit}>
                          <X className="h-4 w-4 text-red-600" />
                        </Button>
                      </div>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="icon" onClick={() => startEdit(comp)}>
                          <Edit2 className="h-4 w-4 text-blue-600" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleRemove(comp.component_id)}>
                          <Trash2 className="h-4 w-4 text-red-600" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={4} className="text-right font-bold">Custo Total Calculado:</TableCell>
              <TableCell className="text-right font-bold">R$ {totalCost.toFixed(4)}</TableCell>
              <TableCell />
            </TableRow>
          </TableFooter>
        </Table>
      </div>
    </div>
  );
};

export default BOMManager;
