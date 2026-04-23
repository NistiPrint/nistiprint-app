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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2, PlusCircle, Edit } from 'lucide-react';
import { toast } from 'sonner';
import TagService from '@/services/TagService';

const tagSchema = z.object({
  name: z.string().min(1, { message: "Nome da tag é obrigatório." }),
});

function TagFormPage() {
  const { id: tagId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!tagId;

  const form = useForm({
    resolver: zodResolver(tagSchema),
    defaultValues: {
      name: '',
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        if (isEditing) {
          const response = await TagService.getById(tagId);
          const data = response.tag;
          form.reset({
            name: data.name || '',
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
  }, [tagId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      const dataToSend = { ...data };

      if (isEditing) {
        await TagService.update(tagId, dataToSend);
        toast.success('Tag atualizada com sucesso!');
      } else {
        await TagService.create(dataToSend);
        toast.success('Tag criada com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4 text-muted-foreground">Carregando formulário...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Tag' : 'Nova Tag'}
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
                  <FormLabel>Nome da Tag *</FormLabel>
                  <FormControl>
                    <Input placeholder="Nome da Tag" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Tag
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

export default TagFormPage;
