import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useAuth } from '@/contexts/AuthContext';
import { estoqueService } from '@/services/EstoqueService';
import ProductService from '@/services/ProductService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2, MinusCircle, PlusCircle, Scale, Shuffle, Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';
import MovimentacaoLotePage from './MovimentacaoLotePage';
import { ProductLevelBadge } from '@/components/produtos/ProductLevelBadge';

// Zod schema for form validation
const movimentoSchema = z.object({
  tipo_movimento: z.enum(["ENTRADA", "SAIDA", "BALANCO", "TRANSFERENCIA"], {
    required_error: "Tipo de movimento é obrigatório."
  }),
  produto_id: z.string().min(1, { message: "Produto é obrigatório." }),
  deposito_id: z.string().min(1, { message: "Depósito de origem é obrigatório." }),
  quantidade: z.preprocess(
    (a) => parseFloat(a),
    z.number().positive({ message: "Quantidade deve ser positiva." })
  ),
  observacao: z.string().max(255, { message: "Observação muito longa." }).optional().nullable(),
  deposito_destino_id: z.string().optional().nullable(), // Only for TRANSFERENCIA
  unit_name: z.string().optional().nullable(), // Optional unit name for conversions
  // user_id will be handled by backend
}).superRefine((data, ctx) => {
    if (data.tipo_movimento === 'TRANSFERENCIA' && !data.deposito_destino_id) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'Depósito de destino é obrigatório para transferência.',
            path: ['deposito_destino_id'],
        });
    }
});


function EstoqueMovimentarPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [depositos, setDepositos] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null); // Currently selected product details

  // Product search states (similar to BOMManager)
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  // Debounce timer
  const [searchTimeout, setSearchTimeout] = useState(null);

  const form = useForm({
    resolver: zodResolver(movimentoSchema),
    defaultValues: {
      tipo_movimento: 'ENTRADA',
      produto_id: '',
      deposito_id: '',
      quantidade: 0,
      observacao: '',
      deposito_destino_id: '',
      unit_name: 'BASE',
    },
  });

  const watchTipoMovimento = form.watch('tipo_movimento');
  const watchProdutoId = form.watch('produto_id');
  const watchDepositoId = form.watch('deposito_id');


  // Fetch initial data (deposits)
  useEffect(() => {
    const fetchInitialData = async () => {
      setLoadingInitialData(true);
      try {
        const data = await estoqueService.getDepositos();
        setDepositos(data.depositos || []);
      } catch (error) {
        toast.error(`Erro ao carregar depósitos: ${error.message}`);
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchInitialData();
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (searchTimeout) {
        clearTimeout(searchTimeout);
      }
    };
  }, [searchTimeout]);

  // Product search effect (debounced)
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (searchTerm.length >= 3 && !selectedProduct) {
        performSearch(searchTerm);
      } else if (searchTerm.length < 3) {
        setSearchResults([]);
      }
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, selectedProduct]);

  // Fetch product details for selected product
  useEffect(() => {
    const fetchProductDetails = async () => {
      if (watchProdutoId) {
        try {
          const data = await ProductService.getById(watchProdutoId);
          const fullProduct = data.produto || data; // Adjust based on API response structure

          // Only update if the product is different from the current selection
          // This prevents overriding the selection made via search
          if (!selectedProduct || selectedProduct.id !== fullProduct.id) {
            setSelectedProduct(fullProduct);
            setSearchTerm(fullProduct.name || fullProduct.nome);
          }
        } catch (error) {
          toast.error(`Erro ao carregar detalhes do produto: ${error.message}`);
          setSelectedProduct(null);
        }
      } else {
        setSelectedProduct(null);
      }
    };
    fetchProductDetails();
  }, [watchProdutoId]);

  // Handle changes to tipo_movimento to reset product selection when needed
  useEffect(() => {
    // When tipo_movimento changes, ensure proper form behavior
    if (watchTipoMovimento !== 'ENTRADA' && watchTipoMovimento !== 'BALANCO') {
      // Clear unit selection when not applicable
      form.setValue('unit_name', 'BASE');
    }
  }, [watchTipoMovimento]);

  // Perform search for products
  const performSearch = async (value) => {
    setIsSearching(true);
    try {
      const results = await ProductService.search(value, {});
      setSearchResults(results.results || []);
    } catch (error) {
      console.error("Error searching products:", error);
      toast.error("Erro ao pesquisar produtos.");
    } finally {
      setIsSearching(false);
    }
  };

  // Handle search input change
  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);

    // If user is typing again, deselect the previously selected product
    if (selectedProduct && value !== selectedProduct.name) {
      setSelectedProduct(null);
    }
  };

  // Select a product from search results
  const selectProduct = async (product) => {
    try {
      // Get full product details to ensure we have unit information
      const productDetails = await ProductService.getById(product.id);
      const fullProduct = productDetails.produto || productDetails;

      // Get unit of measure conversions for the product
      try {
        const response = await fetch(`/api/products/${product.id}/uom-conversions`);
        const conversions = await response.json();
        fullProduct.uom_conversions = conversions.data || conversions; // Handle different response formats
      } catch (conversionError) {
        console.error('Error fetching UoM conversions:', conversionError);
        fullProduct.uom_conversions = []; // Default to empty array if fetch fails
      }

      setSelectedProduct(fullProduct);
      setSearchTerm(fullProduct.name || fullProduct.nome);
      setSearchResults([]);

      // Update the form field with the product ID
      form.setValue('produto_id', product.id);

      // Clear unit selection when product changes
      form.setValue('unit_name', 'BASE');
    } catch (error) {
      console.error('Error fetching product details:', error);
      // Fallback to the basic product info if detailed fetch fails
      setSelectedProduct(product);
      setSearchTerm(product.name);
      setSearchResults([]);

      // Update the form field with the product ID
      form.setValue('produto_id', product.id);

      // Clear unit selection when product changes
      form.setValue('unit_name', 'BASE');
    }
  };

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      // Prepare data for backend
      const payload = {
        ...data,
        quantidade: parseFloat(data.quantidade),
        usuario_id: user?.id,
      };

      // Add unit_name for ENTRADA and BALANCO
      if ((payload.tipo_movimento === 'ENTRADA' || payload.tipo_movimento === 'BALANCO') && selectedProduct) {
        // Use the selected unit from the dropdown
        const selectedUnit = form.getValues('unit_name');
        
        // Only send unit_name if it's a specific conversion (not 'BASE' or empty)
        if (selectedUnit && selectedUnit !== 'BASE') {
          payload.unit_name = selectedUnit;
        } else {
          // If BASE is selected, we don't send unit_name so backend uses base unit
          delete payload.unit_name;
        }
      }

      const result = await estoqueService.registrarMovimentacao(payload);
      toast.success(result.message || 'Movimentação registrada com sucesso!');

      // Reset form after successful submission, but preserve deposit selection
      const depositoId = form.getValues('deposito_id');
      const unitName = form.getValues('unit_name'); // Preserve unit selection
      form.reset({
        tipo_movimento: 'ENTRADA', // Reset to default
        deposito_id: depositoId || '', // Preserve deposit selection
        unit_name: unitName || 'BASE', // Preserve unit selection
        quantidade: 0,
        observacao: '',
        deposito_destino_id: '',
        produto_id: ''
      });

      // Clear product selection state
      setSelectedProduct(null);
      setSearchTerm('');
      setSearchResults([]);

      navigate('/estoque'); // Navigate back to dashboard or history
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando dados iniciais...</div>;

  return (
    <Card className="max-w-6xl mx-auto">
      <CardHeader>
        <CardTitle>Movimentação de Estoque</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="individual" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="individual">Movimentação Individual</TabsTrigger>
            <TabsTrigger value="lote">Movimentação em Lote</TabsTrigger>
          </TabsList>
          <TabsContent value="individual">
            <Card className="max-w-3xl mx-auto">
              <CardContent className="pt-6">
                <Form {...form}>
                  <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                    <FormField
                      control={form.control}
                      name="tipo_movimento"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Tipo de Movimento</FormLabel>
                          <FormControl>
                            <div className="flex flex-row gap-2">
                              <button
                                type="button"
                                className={`relative inline-flex h-9 items-center rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                                  field.value === 'ENTRADA'
                                    ? "bg-primary text-primary-foreground shadow hover:bg-primary/90"
                                    : "border border-input bg-background hover:bg-accent hover:text-accent-foreground"
                                }`}
                                onClick={() => {
                                  field.onChange('ENTRADA');
                                  // Clear product selection when changing movement type
                                  form.setValue('produto_id', '');
                                  form.setValue('unit_name', 'BASE'); // Clear unit selection
                                  setSelectedProduct(null);
                                  setSearchTerm('');
                                  setSearchResults([]);
                                  // Preserve deposit selection
                                }}
                              >
                                <PlusCircle className="h-4 w-4 mr-2 text-green-500" /> Entrada
                              </button>
                              <button
                                type="button"
                                className={`relative inline-flex h-9 items-center rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                                  field.value === 'SAIDA'
                                    ? "bg-primary text-primary-foreground shadow hover:bg-primary/90"
                                    : "border border-input bg-background hover:bg-accent hover:text-accent-foreground"
                                }`}
                                onClick={() => {
                                  field.onChange('SAIDA');
                                  // Clear product selection when changing movement type
                                  form.setValue('produto_id', '');
                                  form.setValue('unit_name', 'BASE'); // Clear unit selection
                                  setSelectedProduct(null);
                                  setSearchTerm('');
                                  setSearchResults([]);
                                  // Preserve deposit selection
                                }}
                              >
                                <MinusCircle className="h-4 w-4 mr-2 text-red-500" /> Saída
                              </button>
                              <button
                                type="button"
                                className={`relative inline-flex h-9 items-center rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                                  field.value === 'BALANCO'
                                    ? "bg-primary text-primary-foreground shadow hover:bg-primary/90"
                                    : "border border-input bg-background hover:bg-accent hover:text-accent-foreground"
                                }`}
                                onClick={() => {
                                  field.onChange('BALANCO');
                                  // Clear product selection when changing movement type
                                  form.setValue('produto_id', '');
                                  form.setValue('unit_name', 'BASE'); // Clear unit selection
                                  setSelectedProduct(null);
                                  setSearchTerm('');
                                  setSearchResults([]);
                                  // Preserve deposit selection
                                }}
                              >
                                <Scale className="h-4 w-4 mr-2 text-blue-500" /> Balanço (Ajuste)
                              </button>
                              <button
                                type="button"
                                className={`relative inline-flex h-9 items-center rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                                  field.value === 'TRANSFERENCIA'
                                    ? "bg-primary text-primary-foreground shadow hover:bg-primary/90"
                                    : "border border-input bg-background hover:bg-accent hover:text-accent-foreground"
                                }`}
                                onClick={() => {
                                  field.onChange('TRANSFERENCIA');
                                  // Clear product selection when changing movement type
                                  form.setValue('produto_id', '');
                                  form.setValue('unit_name', 'BASE'); // Clear unit selection
                                  setSelectedProduct(null);
                                  setSearchTerm('');
                                  setSearchResults([]);
                                  // Preserve deposit selection
                                }}
                              >
                                <Shuffle className="h-4 w-4 mr-2 text-yellow-600" /> Transferência
                              </button>
                            </div>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="deposito_id"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Depósito de Origem</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value || undefined}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Selecione o depósito de origem" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {depositos.map(dep => (
                                <SelectItem key={dep.id} value={dep.id}>{dep.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {watchTipoMovimento === 'TRANSFERENCIA' && (
                      <FormField
                        control={form.control}
                        name="deposito_destino_id"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Depósito de Destino</FormLabel>
                            <Select onValueChange={field.onChange} value={field.value || ""}>
                              <FormControl>
                                <SelectTrigger>
                                  <SelectValue placeholder="Selecione o depósito de destino" />
                                </SelectTrigger>
                              </FormControl>
                              <SelectContent>
                                {depositos
                                  .filter(dep => dep.id !== watchDepositoId) // Cannot transfer to same deposit
                                  .map(dep => (
                                    <SelectItem key={dep.id} value={dep.id}>{dep.name}</SelectItem>
                                  ))}
                              </SelectContent>
                            </Select>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}

                    <FormField
                      control={form.control}
                      name="produto_id"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Produto</FormLabel>
                          <div className="relative w-full">
                            <div className="relative">
                              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                              <Input
                                placeholder="Digite para buscar (nome ou SKU)..."
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

                            {/* Product Search Results Dropdown */}
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

                            {selectedProduct && (
                              <div className="mt-2 p-2 bg-secondary rounded-md text-sm">
                                <div><span className="font-medium">Produto selecionado:</span> {selectedProduct.name || selectedProduct.nome}</div>
                                <div><span className="font-medium">SKU:</span> {selectedProduct.sku_mestre || selectedProduct.sku}</div>
                                {selectedProduct.setor_responsavel_nome && (
                                  <div><span className="font-medium">Setor Responsável:</span> {selectedProduct.setor_responsavel_nome}</div>
                                )}
                              </div>
                            )}
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <FormField
                        control={form.control}
                        name="quantidade"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Quantidade</FormLabel>
                            <FormControl>
                              <Input type="number" step="0.01" {...field} onChange={e => field.onChange(e.target.value ? parseFloat(e.target.value) : 0)} />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {(watchTipoMovimento === 'ENTRADA' || watchTipoMovimento === 'BALANCO') && selectedProduct && (
                        <FormField
                          control={form.control}
                          name="unit_name"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Unidade</FormLabel>
                              <Select onValueChange={field.onChange} value={field.value || 'BASE'}>
                                <FormControl>
                                  <SelectTrigger>
                                    <SelectValue placeholder="Selecione a unidade" />
                                  </SelectTrigger>
                                </FormControl>
                                <SelectContent>
                                  <SelectItem value="BASE">
                                    {selectedProduct.unidade_medida_sigla || selectedProduct.unit_of_measure_symbol 
                                      ? `Unidade (${selectedProduct.unidade_medida_sigla || selectedProduct.unit_of_measure_symbol})` 
                                      : "Unidade Base"}
                                  </SelectItem>
                                  {selectedProduct?.uom_conversions && Array.isArray(selectedProduct.uom_conversions) &&
                                    selectedProduct.uom_conversions
                                      .filter(conv => conv.unitName && conv.unitName.trim() !== "")
                                      .map(conv => (
                                        <SelectItem key={`${conv.id}-${conv.unitName}`} value={conv.unitName}>
                                          {conv.unitName} ({conv.conversionFactor})
                                        </SelectItem>
                                      ))}
                                </SelectContent>
                              </Select>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}
                    </div>

                    <FormField
                      control={form.control}
                      name="observacao"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Observação (Opcional)</FormLabel>
                          <FormControl>
                            <Textarea placeholder="Detalhes adicionais da movimentação..." {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <Button type="submit" disabled={loadingSubmit}>
                      {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Registrar Movimentação
                    </Button>
                  </form>
                </Form>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="lote">
            <Card>
              <CardContent className="pt-6">
                <MovimentacaoLotePage />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

export default EstoqueMovimentarPage;
