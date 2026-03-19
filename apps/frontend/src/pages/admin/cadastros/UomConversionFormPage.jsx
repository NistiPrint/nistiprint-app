import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import ProductSelector from '@/components/ui/ProductSelector';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import UnitService from '@/services/UnitService';
import UomConversionService from '@/services/UomConversionService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Edit, Loader2, PlusCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { z } from 'zod';

const uomConversionSchema = z.object({
  product_id: z.string().min(1, { message: "Produto é obrigatório." }),
  from_unit_id: z.string().min(1, { message: "Unidade de origem é obrigatória." }),
  to_unit_id: z.string().min(1, { message: "Unidade de destino é obrigatória." }),
  conversion_factor: z.preprocess(
    (a) => parseFloat(a),
    z.number().positive({ message: "Fator de conversão deve ser positivo." })
  ),
});

function UomConversionFormPage() {
  const { id: conversionId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [units, setUnits] = useState([]);

  const isEditing = !!conversionId;

  const form = useForm({
    resolver: zodResolver(uomConversionSchema),
    defaultValues: {
      product_id: '',
      from_unit_id: '',
      to_unit_id: '',
      conversion_factor: 1.0,
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        // Fetch units only (products will be loaded by ProductSelector as needed)
        const unitsData = await UnitService.getAll().catch(err => {
            console.error("Erro ao buscar unidades", err);
            return [];
        });

        setUnits(unitsData || []);

        if (isEditing) {
          const response = await UomConversionService.getById(conversionId);
          const data = response.conversion;
          form.reset({
            product_id: data.productId?.toString() || '',
            from_unit_id: data.fromUnitId?.toString() || '',
            to_unit_id: data.toUnitId?.toString() || '',
            conversion_factor: data.conversionFactor || 1.0,
          });
        }
      } catch (error) {
        toast.error(`Erro ao carregar dados: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFormData();
  }, [conversionId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await UomConversionService.update(conversionId, data);
        toast.success('Proporção atualizada com sucesso!');
      } else {
        await UomConversionService.create(data);
        toast.success('Proporção criada com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Proporção...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Proporção' : 'Nova Proporção'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="product_id"
              render={({ field: { onChange: formOnChange, value, ...field } }) => (
                <FormItem>
                  <FormLabel>Produto *</FormLabel>
                  <FormControl>
                    <ProductSelector
                      value={value}
                      onChange={formOnChange}
                      placeholder="Buscar e selecionar produto..."
                      disabled={isEditing}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            
            <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="from_unit_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Unidade Origem *</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value || ''}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Selecione..." />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {units.map(u => (
                            <SelectItem key={u.id} value={u.id.toString()}>{u.name} ({u.symbol})</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="to_unit_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Unidade Destino *</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value || ''}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Selecione..." />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {units.map(u => (
                            <SelectItem key={u.id} value={u.id.toString()}>{u.name} ({u.symbol})</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
            </div>

            <FormField
              control={form.control}
              name="conversion_factor"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Fator de Conversão *</FormLabel>
                  <FormControl>
                    <Input type="number" step="0.000001" {...field} value={field.value || 1} onChange={e => field.onChange(parseFloat(e.target.value))} />
                  </FormControl>
                  <FormDescription>
                    Ex: 1 Unidade Origem = X Unidades Destino
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Proporção
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate('..')} className="flex-1">
                Cancelar
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default UomConversionFormPage;
