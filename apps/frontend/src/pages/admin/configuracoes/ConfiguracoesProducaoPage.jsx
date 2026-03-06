import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import ProductService from '@/services/ProductService';
import { Input } from '@/components/ui/input';
import { Loader2, Settings, Package, Warehouse, Search, Check } from 'lucide-react';
import { toast } from 'sonner';

// Assuming production config schema includes these fields
const producaoConfigSchema = z.object({
  producao_miolos_category_id: z.string().optional(),
  producao_capas_category_id: z.string().optional(),
  producao_capas_impressas_category_id: z.string().optional(),
  default_production_deposit_id: z.string().optional(),
  material_safety_days: z.preprocess(
    (a) => parseFloat(a),
    z.number().int().min(0).optional()
  ),
  sulfite_sheet_product_id: z.string().optional(),
});

function ConfiguracoesProducaoPage() {
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [allCategories, setAllCategories] = useState([]);
  const [allDeposits, setAllDeposits] = useState([]);
  
  // States for simplified product selection
  const [productSearchTerm, setProductSearchTerm] = useState('');
  const [productSearchResults, setProductSearchResults] = useState([]);
  const [isSearchingProduct, setIsSearchingProduct] = useState(false);
  const [selectedProductName, setSelectedProductName] = useState('');


  const form = useForm({
    resolver: zodResolver(producaoConfigSchema),
    defaultValues: {
      producao_miolos_category_id: 'none',
      producao_capas_category_id: 'none',
      producao_capas_impressas_category_id: 'none',
      default_production_deposit_id: 'none',
      material_safety_days: 0,
      sulfite_sheet_product_id: 'none',
    },
  });

  useEffect(() => {
    const fetchConfig = async () => {
      setLoadingInitialData(true);
      try {
        const response = await fetch('/api/v2/configuracoes/producao', {
          headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Erro ao carregar configurações de produção: ${errorText}`);
        }
        const data = await response.json();

        form.reset({
          producao_miolos_category_id: data.producao_miolos_category_id ? data.producao_miolos_category_id.toString() : 'none',
          producao_capas_category_id: data.producao_capas_category_id ? data.producao_capas_category_id.toString() : 'none',
          producao_capas_impressas_category_id: data.producao_capas_impressas_category_id ? data.producao_capas_impressas_category_id.toString() : 'none',
          default_production_deposit_id: data.default_production_deposit_id ? data.default_production_deposit_id.toString() : 'none',
          material_safety_days: data.material_safety_days || 0,
          sulfite_sheet_product_id: data.sulfite_sheet_product_id ? data.sulfite_sheet_product_id.toString() : 'none',
        });
        setAllCategories(data.all_categories || []);
        setAllDeposits(data.all_deposits || []);

        // Fetch selected product name if ID exists
        const sulfiteId = data.sulfite_sheet_product_id;
        if (sulfiteId && sulfiteId !== 'none') {
          try {
            console.log("Fetching Sulfite Product Name for ID:", sulfiteId);
            const prod = await ProductService.getById(sulfiteId);
            console.log("Sulfite Product Data received:", prod);
            
            // Try different name fields based on flattened structure
            const name = prod.name || prod.nome || (prod.produto && (prod.produto.name || prod.produto.nome));
            if (name) {
              setSelectedProductName(name);
            } else {
              setSelectedProductName(`Produto #${sulfiteId}`);
            }
          } catch (e) {
            console.error("Error fetching sulfite product name:", e);
            setSelectedProductName(`Erro ao carregar nome (ID: ${sulfiteId})`);
          }
        } else {
          setSelectedProductName('');
        }

      } catch (error) {
        console.error("Error loading production configs:", error);
        toast.error(`Erro: ${error.message}`);
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchConfig();
  }, [form]);

  // Handle Product Search
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (productSearchTerm.length >= 3) {
        handleProductSearch(productSearchTerm);
      } else {
        setProductSearchResults([]);
      }
    }, 500);
    return () => clearTimeout(delayDebounceFn);
  }, [productSearchTerm]);

  const handleProductSearch = async (term) => {
    setIsSearchingProduct(true);
    try {
      const data = await ProductService.search(term);
      setProductSearchResults(data.results || []);
    } catch (error) {
      console.error("Search error:", error);
    } finally {
      setIsSearchingProduct(false);
    }
  };

  const selectProduct = (product) => {
    form.setValue('sulfite_sheet_product_id', product.id.toString());
    setSelectedProductName(product.name || product.nome);
    setProductSearchResults([]);
    setProductSearchTerm('');
    toast.info(`Produto selecionado: ${product.name || product.nome}`);
  };

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      const dataToSend = { ...data };

      // Convert 'none' values to null for optional ID fields
      const fieldsToNull = [
        'producao_miolos_category_id',
        'producao_capas_category_id',
        'producao_capas_impressas_category_id',
        'default_production_deposit_id',
        'sulfite_sheet_product_id'
      ];

      fieldsToNull.forEach(f => {
        if (dataToSend[f] === 'none') dataToSend[f] = null;
      });

      console.log("Payload sent to backend:", dataToSend);

      const response = await fetch('/api/v2/configuracoes/producao', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(dataToSend),
      });

      const responseText = await response.text();

      if (!response.ok) {
        let errorData = { message: 'Erro desconhecido ao salvar configurações.' };
        try {
          errorData = JSON.parse(responseText);
        } catch (jsonError) {
          errorData.message = responseText || errorData.message;
        }
        throw new Error(errorData.message);
      }

      const result = JSON.parse(responseText);
      toast.success(result.message || 'Configurações de produção salvas com sucesso!');
    } catch (error) {
      console.error("Error during form submission:", error);
      toast.error(`Falha ao salvar configurações: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando configurações de produção...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings className="h-5 w-5" /> Configurações de Produção
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="producao_miolos_category_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Categoria: Miolos</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Nenhuma</SelectItem>
                      {allCategories.map(cat => (
                        <SelectItem key={cat.id} value={cat.id.toString()}>{cat.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="producao_capas_impressas_category_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Categoria: Capas (Impressão)</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Nenhuma</SelectItem>
                      {allCategories.map(cat => (
                        <SelectItem key={cat.id} value={cat.id.toString()}>{cat.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="producao_capas_category_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Categoria: Capas (Acabadas)</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Nenhuma</SelectItem>
                      {allCategories.map(cat => (
                        <SelectItem key={cat.id} value={cat.id.toString()}>{cat.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="default_production_deposit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Depósito Padrão de Produção</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione um depósito" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Nenhum</SelectItem>
                      {allDeposits.map(dep => (
                        <SelectItem key={dep.id} value={dep.id.toString()}>{dep.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="material_safety_days"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Dias de Segurança para Insumos</FormLabel>
                  <FormControl>
                    <Input type="number" {...field} onChange={e => field.onChange(parseInt(e.target.value, 10))} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="sulfite_sheet_product_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Produto Padrão: Folha Sulfite</FormLabel>
                  <div className="space-y-3">
                    {/* Campo 1: Exibição e ID (O que é salvo) */}
                    <div className="flex gap-2 items-center bg-gray-50 p-2 rounded border">
                      <div className="flex-1">
                        <span className="text-xs text-gray-500 block uppercase font-bold">Selecionado (ID: {field.value})</span>
                        <span className="text-sm font-medium">{selectedProductName || 'Nenhum produto vinculado'}</span>
                      </div>
                      {field.value !== 'none' && (
                        <Button 
                          type="button" 
                          variant="ghost" 
                          size="sm" 
                          className="text-red-500 h-8"
                          onClick={() => {
                            field.onChange('none');
                            setSelectedProductName('');
                          }}
                        >
                          Remover
                        </Button>
                      )}
                    </div>

                    {/* Campo 2: Pesquisa (Para encontrar novo ID) */}
                    <div className="relative">
                      <div className="relative">
                        <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                        <Input
                          placeholder="Pesquisar por nome ou SKU para alterar..."
                          value={productSearchTerm}
                          onChange={(e) => setProductSearchTerm(e.target.value)}
                          className="pl-8"
                        />
                        {isSearchingProduct && (
                          <div className="absolute right-3 top-2.5">
                            <Loader2 className="h-4 w-4 animate-spin text-primary" />
                          </div>
                        )}
                      </div>

                      {productSearchResults.length > 0 && (
                        <div className="absolute z-50 w-full mt-1 bg-white border rounded-md shadow-lg max-h-60 overflow-auto">
                          {productSearchResults.map(prod => (
                            <div
                              key={prod.id}
                              className="flex items-center justify-between p-3 hover:bg-blue-50 cursor-pointer border-b last:border-0"
                              onClick={() => selectProduct(prod)}
                            >
                              <div>
                                <div className="font-medium text-sm">{prod.name || prod.nome}</div>
                                <div className="text-xs text-gray-500">SKU: {prod.sku}</div>
                              </div>
                              <Button size="xs" variant="outline" className="h-7 text-[10px]">
                                <Check className="h-3 w-3 mr-1" /> Selecionar
                              </Button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit" disabled={loadingSubmit}>
              {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Salvar Configurações
            </Button>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default ConfiguracoesProducaoPage;