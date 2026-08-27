import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '@/components/ui/card';
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { MapPin, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import PontoColetaService from '@/services/PontoColetaService';

const formSchema = z.object({
  nome: z.string().min(1, 'Nome é obrigatório'),
  horario_fechamento: z.string().min(1, 'Informe a hora em que o ponto fecha'),
  endereco: z.string().optional(),
  ativo: z.boolean().default(true),
});

function PontoColetaFormPage() {
  const { id } = useParams();
  const isEditing = !!id;
  const navigate = useNavigate();
  const [loading, setLoading] = useState(isEditing);
  const [loadingSubmit, setLoadingSubmit] = useState(false);

  const form = useForm({
    resolver: zodResolver(formSchema),
    defaultValues: {
      nome: '',
      horario_fechamento: '17:00',
      endereco: '',
      ativo: true,
    },
  });

  useEffect(() => {
    if (isEditing) {
      const fetchPonto = async () => {
        try {
          const data = await PontoColetaService.getById(id);
          if (data) {
            form.reset({
              nome: data.nome,
              horario_fechamento: data.horario_fechamento,
              endereco: data.endereco || '',
              ativo: data.ativo,
            });
          }
        } catch (e) {
          toast.error(`Erro ao carregar ponto de coleta: ${e.message}`);
          navigate('..');
        } finally {
          setLoading(false);
        }
      };
      fetchPonto();
    }
  }, [id, isEditing, form, navigate]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await PontoColetaService.update(id, data);
        toast.success('Ponto de coleta atualizado com sucesso!');
      } else {
        await PontoColetaService.create(data);
        toast.success('Ponto de coleta criado com sucesso!');
      }
      navigate('..');
    } catch (e) {
      toast.error(`Erro ao salvar ponto de coleta: ${e.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPin className="h-5 w-5" />
            {isEditing ? 'Editar Ponto de Coleta' : 'Novo Ponto de Coleta'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                control={form.control}
                name="nome"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Nome do Ponto</FormLabel>
                    <FormControl>
                      <Input placeholder="Ex: Agência Correios Central" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="horario_fechamento"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Horário em que o ponto fecha</FormLabel>
                    <FormControl>
                      <Input type="time" {...field} />
                    </FormControl>
                    {/* Ponto de coleta não tem hora de corte: corte é regra de
                        pertencimento do lote, e quem tem corte é a janela. Aqui
                        é a hora em que a porta fecha — e é ela que vira o prazo
                        de entrega das janelas que usam este ponto. */}
                    <p className="text-xs text-muted-foreground">
                      É o prazo de entrega das janelas que entregam neste ponto.
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="endereco"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Endereço</FormLabel>
                    <FormControl>
                      <Textarea placeholder="Endereço completo..." {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="ativo"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between rounded-md border p-4 shadow-sm">
                    <div className="space-y-0.5">
                      <FormLabel>Ativo</FormLabel>
                    </div>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />

              <div className="flex gap-4 pt-4">
                <Button type="submit" disabled={loadingSubmit} className="flex-1">
                  {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {isEditing ? 'Atualizar' : 'Criar'}
                </Button>
                <Button type="button" variant="outline" onClick={() => navigate('..')} className="flex-1">
                  Cancelar
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}

export default PontoColetaFormPage;
