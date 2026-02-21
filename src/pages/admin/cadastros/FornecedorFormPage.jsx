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
import FornecedorService from '@/services/FornecedorService';

const fornecedorSchema = z.object({
  nome_razao_social: z.string().min(1, { message: "Nome/Razão Social é obrigatório." }),
  cpf_cnpj: z.string().optional().nullable(),
  email: z.string().email({ message: "Email inválido." }).optional().or(z.literal('')).nullable(),
  telefone: z.string().optional().nullable(),
  ativo: z.boolean().default(true),
});

function FornecedorFormPage() {
  const { id: fornecedorId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const isEditing = !!fornecedorId;

  const form = useForm({
    resolver: zodResolver(fornecedorSchema),
    defaultValues: {
      nome_razao_social: '',
      cpf_cnpj: '',
      email: '',
      telefone: '',
      ativo: true,
    },
  });

  useEffect(() => {
    const fetchFornecedor = async () => {
      if (!isEditing) {
        setLoadingInitialData(false);
        return;
      }
      setLoadingInitialData(true);
      try {
        const response = await FornecedorService.getById(fornecedorId);
        form.reset(response.fornecedor);
      } catch (error) {
        toast.error(`Erro ao carregar fornecedor: ${error.message}`);
        navigate('..');
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchFornecedor();
  }, [fornecedorId, navigate, form, isEditing]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await FornecedorService.update(fornecedorId, data);
        toast.success('Fornecedor atualizado com sucesso!');
      } else {
        await FornecedorService.create(data);
        toast.success('Fornecedor criado com sucesso!');
      }
      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData && isEditing) return <div className="text-center py-4 text-muted-foreground">Carregando Fornecedor...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Fornecedor' : 'Novo Fornecedor'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="nome_razao_social"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Nome / Razão Social *</FormLabel>
                  <FormControl>
                    <Input placeholder="Nome ou Razão Social" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="cpf_cnpj"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>CPF / CNPJ</FormLabel>
                  <FormControl>
                    <Input placeholder="CPF ou CNPJ" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" placeholder="email@exemplo.com" {...field} value={field.value || ''} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="telefone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Telefone</FormLabel>
                  <FormControl>
                    <Input placeholder="(XX) XXXXX-XXXX" {...field} value={field.value || ''} />
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
                    <FormLabel>Ativo</FormLabel>
                    <FormDescription>
                      Marque para indicar que este fornecedor está ativo.
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />
            <div className="flex gap-4">
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Fornecedor
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

export default FornecedorFormPage;