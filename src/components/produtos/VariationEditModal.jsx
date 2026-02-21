import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage, FormDescription } from '@/components/ui/form';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, Save } from 'lucide-react';
import { toast } from 'sonner';
import ProductService from '@/services/ProductService';
import ArtworkManager from './ArtworkManager';

// Schema atualizado para edição de variação com campos de formato e herança
const variationSchema = z.object({
  sku: z.string().min(1, "SKU é obrigatório"),
  name: z.string().min(1, "Nome é obrigatório"),
  cost_price: z.number().min(0),
  price: z.number().min(0, "Preço de venda deve ser maior ou igual a zero"),
  stock_min: z.number().int().min(0).optional(),
  stock_max: z.number().int().min(0).optional(),
  status: z.enum(['ativo', 'inativo', 'rascunho']),
  weight: z.number().min(0).optional(), // Peso em kg
  formato: z.enum(["simples", "com_variacao", "variacao", "composicao", "kit"], { message: "Formato do produto inválido." }),
  herdar_dados_pai: z.boolean().default(true),
  herdar_bom_pai: z.boolean().default(true),
  // Campos adicionais podem ser mapeados para atributos JSONB no backend
});

const VariationEditModal = ({ isOpen, onClose, variationId, parentProduct, onSaveSuccess }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [activeTab, setActiveTab] = useState("general");
  const [currentVariation, setCurrentVariation] = useState(null);

  const form = useForm({
    resolver: zodResolver(variationSchema),
    defaultValues: {
      sku: '',
      name: '',
      cost_price: 0,
      price: 0,
      stock_min: 0,
      stock_max: 0,
      status: 'ativo',
      weight: 0,
      formato: 'variacao',
      herdar_dados_pai: true,
      herdar_bom_pai: true
    }
  });

  useEffect(() => {
    if (isOpen && variationId) {
      loadVariationData();
    }
  }, [isOpen, variationId]);

  const loadVariationData = async () => {
    setIsLoading(true);
    try {
      const data = await ProductService.getById(variationId);
      const product = data.produto;
      setCurrentVariation(product);

      form.reset({
        sku: product.sku || '',
        name: product.name || '',
        cost_price: parseFloat(product.cost_price || 0),
        price: parseFloat(product.price || product.preco_venda || 0),
        stock_min: product.stock_min || 0,
        stock_max: product.stock_max || 0,
        status: product.status || 'ativo',
        weight: parseFloat(product.atributos?.weight || 0),
        formato: product.formato || 'variacao',
        herdar_dados_pai: product.herdar_dados_pai !== undefined ? product.herdar_dados_pai : true,
        herdar_bom_pai: product.herdar_bom_pai !== undefined ? product.herdar_bom_pai : true
      });
    } catch (error) {
      console.error("Erro ao carregar variação:", error);
      toast.error("Erro ao carregar dados da variação.");
      onClose();
    } finally {
      setIsLoading(false);
    }
  };

  const handleSnapshotFromParent = async () => {
    if (!currentVariation?.parent_id) return;

    try {
      const parentData = await ProductService.getById(currentVariation.parent_id);
      const parent = parentData.produto;

      // Update form fields with parent data
      form.setValue('name', parent.name || '');
      form.setValue('cost_price', parseFloat(parent.cost_price || 0));
      form.setValue('price', parseFloat(parent.price || parent.preco_venda || 0));
      form.setValue('stock_min', parent.stock_min || 0);
      form.setValue('stock_max', parent.stock_max || 0);
      form.setValue('status', parent.status || 'ativo');
      form.setValue('weight', parseFloat(parent.atributos?.weight || 0));
    } catch (error) {
      console.error("Error getting parent data for snapshot:", error);
      toast.error("Erro ao obter dados do produto pai para cópia.");
    }
  };

  const onSubmit = async (data) => {
    setIsSaving(true);
    try {
      // Preparar payload
      // Mapear campos específicos para atributos JSON se necessário
      const payload = {
        sku: data.sku,
        name: data.name,
        cost_price: data.cost_price,
        price: data.price,
        stock_min: data.stock_min,
        stock_max: data.stock_max,
        status: data.status,
        formato: data.formato,
        herdar_dados_pai: data.herdar_dados_pai,
        herdar_bom_pai: data.herdar_bom_pai,
        // Campos extras vão para atributos via lógica do backend ou explícita aqui se o backend suportar
        material_type: 'produto_acabado', // Variações geralmente herdam ou são produtos acabados
        // Se o backend suportar atualização parcial de atributos JSONB:
        weight: data.weight
      };

      await ProductService.update(variationId, payload);
      toast.success("Variação atualizada com sucesso!");
      if (onSaveSuccess) onSaveSuccess();
      onClose();
    } catch (error) {
      console.error("Erro ao salvar variação:", error);
      toast.error("Erro ao salvar variação: " + (error.response?.data?.error || error.message));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[700px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Editar Variação</DialogTitle>
          <DialogDescription>
            Edite os detalhes específicos desta variação (SKU {form.getValues('sku')}).
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : (
          <Form {...form}>
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="general">Geral</TabsTrigger>
                <TabsTrigger value="media">Multimídia & Arquivos</TabsTrigger>
              </TabsList>

              <TabsContent value="general" className="py-4 space-y-4">
                <form id="variation-form" onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="sku"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>SKU da Variação</FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              disabled={form.watch('herdar_dados_pai')}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="status"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Status</FormLabel>
                          <select
                            className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                            {...field}
                            disabled={form.watch('herdar_dados_pai')}
                          >
                            <option value="ativo">Ativo</option>
                            <option value="inativo">Inativo</option>
                            <option value="rascunho">Rascunho</option>
                          </select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <FormField
                    control={form.control}
                    name="name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nome Completo</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            disabled={form.watch('herdar_dados_pai')}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="formato"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Formato do Produto</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value}
                          >
                            <FormControl>
                              <SelectTrigger>
                                <SelectValue placeholder="Selecione o formato do produto" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value="simples">Simples</SelectItem>
                              <SelectItem value="com_variacao">Com Variação (Pai)</SelectItem>
                              <SelectItem value="variacao">Variação (Filho)</SelectItem>
                              <SelectItem value="composicao">Composição (Manufatura)</SelectItem>
                              <SelectItem value="kit">Kit (Comercial)</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="cost_price"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Custo (R$)</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="0.01"
                              {...field}
                              onChange={e => field.onChange(parseFloat(e.target.value))}
                              disabled={form.watch('herdar_dados_pai')}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="price"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Preço de Venda (R$)</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="0.01"
                              {...field}
                              onChange={e => field.onChange(parseFloat(e.target.value))}
                              disabled={form.watch('herdar_dados_pai')}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {/* Inheritance Controls for Variations */}
                  <div className="border rounded-lg p-4 mt-4">
                    <h3 className="text-lg font-medium mb-4 text-primary">Controles de Herança</h3>

                    <FormField
                      control={form.control}
                      name="herdar_dados_pai"
                      render={({ field }) => (
                        <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4 mb-4">
                          <FormControl>
                            <Checkbox
                              checked={field.value}
                              onCheckedChange={(checked) => {
                                field.onChange(checked);
                                if (!checked) {
                                  // If unchecking inheritance, populate with parent data (snapshot)
                                  handleSnapshotFromParent();
                                }
                              }}
                            />
                          </FormControl>
                          <div className="space-y-1 leading-none">
                            <FormLabel>
                              Utilizar descrição, categoria e tags do produto pai
                            </FormLabel>
                            <FormDescription>
                              Marque para herdar dados do produto pai. Desative para usar valores personalizados.
                            </FormDescription>
                          </div>
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="herdar_bom_pai"
                      render={({ field }) => (
                        <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                          <FormControl>
                            <Checkbox
                              checked={field.value}
                              onCheckedChange={field.onChange}
                            />
                          </FormControl>
                          <div className="space-y-1 leading-none">
                            <FormLabel>
                              Utilizar a mesma estrutura (BOM) do produto pai
                            </FormLabel>
                            <FormDescription>
                              Marque para herdar a estrutura de composição do produto pai.
                            </FormDescription>
                          </div>
                        </FormItem>
                      )}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="stock_min"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Estoque Mínimo</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              {...field}
                              onChange={e => field.onChange(parseInt(e.target.value))}
                              disabled={form.watch('herdar_dados_pai')}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="stock_max"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Estoque Máximo</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              {...field}
                              onChange={e => field.onChange(parseInt(e.target.value))}
                              disabled={form.watch('herdar_dados_pai')}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  <FormField
                    control={form.control}
                    name="weight"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Peso (kg)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            step="0.001"
                            {...field}
                            onChange={e => field.onChange(parseFloat(e.target.value))}
                            disabled={form.watch('herdar_dados_pai')}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </form>
              </TabsContent>

              <TabsContent value="media" className="py-4">
                <div className="space-y-4">
                    <div className="bg-muted p-4 rounded-md mb-4">
                        <p className="text-sm text-muted-foreground">
                            Gerencie as imagens específicas desta variação. Isso ajudará o cliente a identificar a cor/modelo exato.
                        </p>
                    </div>
                    {/* Reutilizando ArtworkManager para a variação */}
                    <ArtworkManager productId={variationId} />
                </div>
              </TabsContent>
            </Tabs>
          </Form>
        )}

        <DialogFooter className="mt-6">
          <Button variant="outline" onClick={onClose} disabled={isSaving}>
            Cancelar
          </Button>
          <Button onClick={form.handleSubmit(onSubmit)} disabled={isSaving || isLoading}>
            {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Salvar Alterações
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default VariationEditModal;
