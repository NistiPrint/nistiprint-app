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
  FormDescription,
} from '@/components/ui/form';
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, PlusCircle, Edit } from 'lucide-react';
import { toast } from 'sonner';
import PlataformaService from '@/services/PlataformaService';

const plataformaSchema = z.object({
  nome: z.string().min(1, { message: "Nome é obrigatório." }),
  ativo: z.boolean().default(true),
});

function PlataformaFormPage() {
  const { id: plataformaId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!plataformaId;

  const form = useForm({
    resolver: zodResolver(plataformaSchema),
    defaultValues: {
      nome: '',
      ativo: true,
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      if (!isEditing) {
        setLoadingInitialData(false);
        return;
      }
      setLoadingInitialData(true);
      try {
        const response = await PlataformaService.getById(plataformaId);
        form.reset({
          nome: response.plataforma.nome || '',
          ativo: response.plataforma.ativo ?? true,
        });
      } catch (error) {
        toast.error(`Erro: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFormData();
  }, [plataformaId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await PlataformaService.update(plataformaId, data);
        toast.success('Plataforma atualizada com sucesso!');
      } else {
        await PlataformaService.create(data);
        toast.success('Plataforma criada com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Plataforma...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Plataforma' : 'Nova Plataforma'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="nome"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nome da Plataforma *</FormLabel>
                  <FormControl>
                    <Input placeholder="Ex: Shopee, Mercado Livre" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="ativo"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4 shadow-sm">
                  <FormControl>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Ativa</FormLabel>
                    <FormDescription>
                      Marque para indicar que esta plataforma está disponível para uso.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Plataforma
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

export default PlataformaFormPage;