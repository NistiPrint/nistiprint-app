import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Loader2, PlusCircle, Edit } from 'lucide-react';
import { toast } from 'sonner';
import UnitService from '@/services/UnitService';

const unidadeMedidaSchema = z.object({
  name: z.string().min(1, { message: "Nome da unidade é obrigatório." }),
  symbol: z.string().min(1, { message: "Símbolo é obrigatório." }),
});

function UnidadeMedidaFormPage() {
  const { id: unidadeId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!unidadeId;

  const form = useForm({
    resolver: zodResolver(unidadeMedidaSchema),
    defaultValues: {
      name: '',
      symbol: '',
    },
  });

  useEffect(() => {
    const fetchUnidade = async () => {
      if (!isEditing) {
        setLoadingInitialData(false);
        return;
      }
      setLoadingInitialData(true);
      try {
        const response = await UnitService.getById(unidadeId);
        form.reset(response.unidade);
      } catch (error) {
        toast.error(`Erro ao carregar unidade de medida: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchUnidade();
  }, [unidadeId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await UnitService.update(unidadeId, data);
        toast.success('Unidade de medida atualizada com sucesso!');
      } else {
        await UnitService.create(data);
        toast.success('Unidade de medida criada com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Unidade de Medida...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Unidade de Medida' : 'Nova Unidade de Medida'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nome da Unidade *</FormLabel>
                  <FormControl>
                    <Input placeholder="Ex: Metros, Quilogramas" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="symbol"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Símbolo *</FormLabel>
                  <FormControl>
                    <Input placeholder="Ex: m, kg" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Unidade
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

export default UnidadeMedidaFormPage;
