import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { sectorSchema } from '@/schemas/sectorSchemas';
import SectorService from '@/services/SectorService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Edit, Loader2, PlusCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

function SetorFormPage() {
  const { id: setorId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!setorId;

  const form = useForm({
    resolver: zodResolver(sectorSchema),
    defaultValues: {
      nome: '',
      descricao: '',
      ativo: true,
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        if (setorId) {
          const setorResponse = await SectorService.getById(parseInt(setorId));
          form.reset({
            nome: setorResponse.nome || '',
            descricao: setorResponse.descricao || '',
            ativo: setorResponse.ativo || true,
          });
        }
      } catch (error) {
        toast.error(`Erro ao carregar dados: ${error.message}`);
        navigate('/sistema/setores');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFormData();
  }, [setorId, navigate, form]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await SectorService.update(parseInt(setorId), data);
        toast.success('Setor atualizado com sucesso!');
      } else {
        await SectorService.create(data);
        toast.success('Setor criado com sucesso!');
      }

      navigate('/sistema/setores');
    } catch (error) {
      toast.error(`Erro: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) {
    return <div className="text-center py-4">Carregando setor...</div>;
  }

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Setor' : 'Novo Setor'}
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
                  <FormLabel>Nome *</FormLabel>
                  <FormControl>
                    <Input placeholder="Nome do setor" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="descricao"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Descrição</FormLabel>
                  <FormControl>
                    <Input placeholder="Descrição opcional do setor" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="ativo"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center space-x-3 space-y-0">
                  <FormControl>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={field.onChange}
                    />
                  </FormControl>
                  <div className="space-y-1 leading-none">
                    <FormLabel>Setor ativo</FormLabel>
                  </div>
                </FormItem>
              )}
            />

            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditing ? 'Atualizar' : 'Criar'} Setor
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate('/sistema/setores')}
                className="flex-1"
              >
                Cancelar
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default SetorFormPage;
