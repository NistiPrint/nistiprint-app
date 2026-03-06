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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAuth } from '@/contexts/AuthContext';
import { estoqueService } from '@/services/EstoqueService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2, PlusCircle, Trash2, Warehouse } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFieldArray, useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

// Zod schema for individual adjustment item
const adjustmentItemSchema = z.object({
  id: z.string(), // product_id
  name: z.string(), // product_name for display
  sku: z.string().optional(),
  setor_responsavel_nome: z.string().optional(), // nome do setor responsável
  system_quantity: z.number().nullable(),
  counted: z.preprocess(
    (a) => parseFloat(a),
    z.number().min(0, { message: "Contagem não pode ser negativa." })
  ),
  variance: z.number().optional(), // Calculated on client side
});

// Zod schema for the entire adjustment form
const ajusteInventarioSchema = z.object({
  deposito_id: z.string().min(1, { message: "Depósito é obrigatório." }),
  adjustments: z.array(adjustmentItemSchema).min(1, { message: "Adicione pelo menos um produto para ajuste." }),
});

function EstoqueAjustePage() {
  const { user } = useAuth();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [depositos, setDepositos] = useState([]);
  const [productSearchTerm, setProductSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedDepositoId, setSelectedDepositoId] = useState('');


  const form = useForm({
    resolver: zodResolver(ajusteInventarioSchema),
    defaultValues: {
      deposito_id: '',
      adjustments: [],
    },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "adjustments",
  });

  const watchDepositoId = form.watch('deposito_id');
  useEffect(() => {
    setSelectedDepositoId(watchDepositoId);
    // Clear adjustments when deposit changes
    form.setValue('adjustments', []);
  }, [watchDepositoId, form]);


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

  // Handle product search
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (productSearchTerm.length > 2 && selectedDepositoId) {
        handleProductSearch(productSearchTerm, selectedDepositoId);
      } else {
        setSearchResults([]);
      }
    }, 500); // Debounce search

    return () => clearTimeout(delayDebounceFn);
  }, [productSearchTerm, selectedDepositoId]);


  const handleProductSearch = async (searchTerm, depositoId) => {
    if (!depositoId) return; // Cannot search products without a selected deposit
    try {
      const data = await estoqueService.searchProdutos(searchTerm, depositoId);
      setSearchResults(data.results || []);
    } catch (error) {
      toast.error(`Erro na busca de produtos: ${error.message}`);
      setSearchResults([]);
    }
  };

  const handleAddProductToAdjust = (product) => {
    const existing = fields.find(item => item.id === product.id);
    if (existing) {
      toast.info('Produto já adicionado para ajuste.');
      return;
    }
    append({
      id: product.id,
      name: product.name,
      sku: product.sku,
      setor_responsavel_nome: product.setor_responsavel_nome, // Adicionando o nome do setor responsável
      system_quantity: product.saldo, // Assuming 'saldo' from API is system quantity
      counted: 0,
    });
    setProductSearchTerm(''); // Clear search input
    setSearchResults([]); // Clear search results
  };

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      const payload = {
        deposito_id: data.deposito_id,
        usuario_id: user?.id,
        adjustments: data.adjustments.map(adj => ({
          id: adj.id,
          counted: adj.counted,
          system: adj.system_quantity,
          variance: adj.counted - adj.system_quantity,
        })),
      };

      const result = await estoqueService.realizarAjuste(payload);
      toast.success(result.message || 'Ajustes aplicados com sucesso!');
      form.reset({ deposito_id: data.deposito_id, adjustments: [] }); // Reset form, keep deposit selected
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando dados iniciais...</div>;

  return (
    <Card className="max-w-4xl mx-auto">
      <CardHeader>
        <CardTitle>Ajuste de Inventário</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="deposito_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Depósito para Ajuste</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value || ""} disabled={fields.length > 0}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione o depósito" />
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

            {selectedDepositoId && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <PlusCircle className="h-5 w-5" /> Adicionar Produtos
                </h3>
                <Input
                  placeholder="Buscar produto por SKU ou nome..."
                  value={productSearchTerm}
                  onChange={(e) => setProductSearchTerm(e.target.value)}
                  disabled={!selectedDepositoId}
                />
                {searchResults.length > 0 && (
                  <div className="border rounded-md max-h-40 overflow-y-auto">
                    {searchResults.map(product => (
                      <div
                        key={product.id}
                        className="flex items-center justify-between p-2 hover:bg-muted cursor-pointer border-b last:border-b-0"
                        onClick={() => handleAddProductToAdjust(product)}
                      >
                        <span>{product.text}</span>
                        {product.saldo !== undefined && <span className="text-muted-foreground">Sistema: {product.saldo}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {fields.length > 0 && (
              <div className="space-y-4">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <Warehouse className="h-5 w-5" /> Itens para Ajuste
                </h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Produto (SKU)</TableHead>
                      <TableHead>Setor Responsável</TableHead>
                      <TableHead className="text-right">Qtd. Sistema</TableHead>
                      <TableHead className="text-right">Qtd. Contada</TableHead>
                      <TableHead className="text-right">Variação</TableHead>
                      <TableHead className="text-right">Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {fields.map((item, index) => (
                      <TableRow key={item.id}>
                        <TableCell>
                          <div className="font-medium">{item.name}</div>
                          <div className="text-sm text-muted-foreground">SKU: {item.sku}</div>
                        </TableCell>
                        <TableCell>
                          {form.watch(`adjustments.${index}.setor_responsavel_nome`) || '-'}
                        </TableCell>
                        <TableCell className="text-right">{item.system_quantity}</TableCell>
                        <TableCell className="text-right w-32">
                          <FormField
                            control={form.control}
                            name={`adjustments.${index}.counted`}
                            render={({ field }) => (
                              <FormItem className="mb-0">
                                <FormControl>
                                  <Input
                                    type="number"
                                    step="0.01"
                                    {...field}
                                    value={field.value || ''}
                                    onChange={(e) => {
                                      const val = e.target.value ? parseFloat(e.target.value) : 0;
                                      field.onChange(val);
                                      form.setValue(`adjustments.${index}.variance`, val - item.system_quantity);
                                    }}
                                    className="text-right"
                                  />
                                </FormControl>
                                <FormMessage />
                              </FormItem>
                            )}
                          />
                        </TableCell>
                        <TableCell className="text-right">
                          {form.watch(`adjustments.${index}.counted`) - item.system_quantity || 0}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="destructive" size="icon" onClick={() => remove(index)}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            <Button type="submit" disabled={loadingSubmit || fields.length === 0}>
              {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Aplicar Ajustes
            </Button>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default EstoqueAjustePage;
