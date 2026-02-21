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
import { Loader2, ShoppingBag } from 'lucide-react';
import { toast } from 'sonner';

const blingConfigSchema = z.object({
  default_bling_account_id: z.string().optional(),
});

function ConfiguracoesBlingPage() {
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [allBlingAccounts, setAllBlingAccounts] = useState([]);

  const form = useForm({
    resolver: zodResolver(blingConfigSchema),
    defaultValues: {
      default_bling_account_id: 'none',
    },
  });

  useEffect(() => {
    const fetchConfig = async () => {
      setLoadingInitialData(true);
      try {
        const response = await fetch('/api/v2/configuracoes/bling', {
          headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error('Erro ao carregar configurações do Bling.');
        const data = await response.json();
        
        form.reset({
          default_bling_account_id: data.selected_bling_account_id ? data.selected_bling_account_id.toString() : 'none',
        });
        setAllBlingAccounts(data.all_bling_accounts || []);

      } catch (error) {
        toast.error(`Erro: ${error.message}`);
      } finally {
        setLoadingInitialData(false);
      }
    };
    fetchConfig();
  }, [form]);

        const onSubmit = async (data) => {
          setLoadingSubmit(true);
          try {
            const dataToSend = { ...data };
            if (dataToSend.default_bling_account_id === 'none') {
              dataToSend.default_bling_account_id = '';
            }
            const response = await fetch('/api/v2/configuracoes/bling', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
              },
              body: JSON.stringify(dataToSend),
            });
      
            if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.message || 'Erro ao salvar configurações.');
            }
      const result = await response.json();
      toast.success(result.message || 'Configurações salvas com sucesso!');
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) return <div className="text-center py-4">Carregando configurações do Bling...</div>;

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShoppingBag className="h-5 w-5" /> Configurações Bling
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            <FormField
              control={form.control}
              name="default_bling_account_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Conta Bling Padrão</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione uma conta Bling" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Nenhuma</SelectItem>
                      {allBlingAccounts.map(account => (
                        <SelectItem key={account.id} value={account.id.toString()}>{account.nome}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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

export default ConfiguracoesBlingPage;
