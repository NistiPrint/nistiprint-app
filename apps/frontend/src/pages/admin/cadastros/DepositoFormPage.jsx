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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2, PlusCircle, Edit } from 'lucide-react';
import { toast } from 'sonner';
import DepositoService from '@/services/DepositoService';

const depositoSchema = z.object({
  nome: z.string().min(1, { message: "Nome do depósito é obrigatório." }),
  tipo: z.enum(["MATERIA_PRIMA", "PRODUCAO", "ACABADO"], {
    required_error: "Tipo de depósito é obrigatório."
  }),
  ativo: z.boolean().default(true),
});

function DepositoFormPage() {
  const { id: depositoId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!depositoId;

  const form = useForm({
    resolver: zodResolver(depositoSchema),
    defaultValues: {
      nome: '',
      tipo: 'MATERIA_PRIMA',
      ativo: true,
    },
  });

  useEffect(() => {
    const fetchDeposito = async () => {
      if (!isEditing) {
        setLoadingInitialData(false);
        return;
      }
      setLoadingInitialData(true);
      try {
        const response = await DepositoService.getById(depositoId);
        form.reset(response.deposito);
      } catch (error) {
        toast.error(`Erro ao carregar depósito: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchDeposito();
  }, [depositoId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await DepositoService.update(depositoId, data);
        toast.success('Depósito atualizado com sucesso!');
      } else {
        await DepositoService.create(data);
        toast.success('Depósito criado com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Depósito...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Depósito' : 'Novo Depósito'}
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
                  <FormLabel>Nome do Depósito *</FormLabel>
                  <FormControl>
                    <Input placeholder="Nome do Depósito" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="tipo"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tipo de Depósito *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione o tipo" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="MATERIA_PRIMA">Matéria Prima</SelectItem>
                      <SelectItem value="PRODUCAO">Produção</SelectItem>
                      <SelectItem value="ACABADO">Acabado</SelectItem>
                    </SelectContent>
                  </Select>
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
                    <FormLabel>Ativo</FormLabel>
                    <FormDescription>
                      Marque para indicar que este depósito está ativo.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Depósito
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

export default DepositoFormPage;
