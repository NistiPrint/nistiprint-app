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
import PageActions from '@/components/ui/PageActions';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { userSchema, userUpdateSchema } from '@/schemas/userSchemas';
import SectorService from '@/services/SectorService';
import UserService from '@/services/UserService';
import { zodResolver } from '@hookform/resolvers/zod';
import { Edit, Loader2, PlusCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

function UsuarioFormPage() {
  const { id: usuarioId } = useParams();
  const navigate = useNavigate();
  const [loadingInitialData, setLoadingInitialData] = useState(true);
  const [loadingSubmit, setLoadingSubmit] = useState(false);
  const [setores, setSetores] = useState([]);

  const isEditing = !!usuarioId;
  const schema = isEditing ? userUpdateSchema : userSchema;

  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      nome: '',
      email: '',
      senha: '',
      setor_id: '',
      ativo: true,
      is_admin: false,
    },
  });

  useEffect(() => {
    const fetchFormData = async () => {
      setLoadingInitialData(true);
      try {
        // Fetch setores
        const setoresData = await SectorService.getAll();
        setSetores(setoresData);

        if (usuarioId) {
          const usuarioResponse = await UserService.getById(parseInt(usuarioId));
          form.reset({
            nome: usuarioResponse.nome || '',
            email: usuarioResponse.email || '',
            setor_id: usuarioResponse.setor_id || '',
            ativo: usuarioResponse.ativo || true,
            is_admin: usuarioResponse.is_admin || false,
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
  }, [usuarioId, navigate, form]);

  const onSubmit = async (data) => {
    setLoadingSubmit(true);
    try {
      if (isEditing) {
        await UserService.update(parseInt(usuarioId), data);
        toast.success('Usuário atualizado com sucesso!');
      } else {
        await UserService.create(data);
        toast.success('Usuário criado com sucesso!');
      }

      navigate('..');
    } catch (error) {
      toast.error(`Erro: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoadingSubmit(false);
    }
  };

  if (loadingInitialData) {
    return <div className="text-center py-4">Carregando formulário...</div>;
  }

  return (
    <Card className="max-w-xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {isEditing ? <Edit className="h-5 w-5" /> : <PlusCircle className="h-5 w-5" />}
          {isEditing ? 'Editar Usuário' : 'Novo Usuário'}
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
                    <Input placeholder="Nome completo" {...field} />
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
                  <FormLabel>Email *</FormLabel>
                  <FormControl>
                    <Input type="email" placeholder="email@exemplo.com" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {!isEditing && (
              <FormField
                control={form.control}
                name="senha"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Senha *</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="Mínimo 6 caracteres" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="setor_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Setor *</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value?.toString()}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione um setor" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {setores.map((setor) => (
                        <SelectItem key={setor.id} value={setor.id.toString()}>
                          {setor.nome}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="space-y-4">
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
                      <FormLabel>Usuário ativo</FormLabel>
                    </div>
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="is_admin"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center space-x-3 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                    <div className="space-y-1 leading-none">
                      <FormLabel>Administrador</FormLabel>
                    </div>
                  </FormItem>
                )}
              />
            </div>

            <PageActions>
              <Button type="submit" disabled={loadingSubmit} className="flex-1">
                {loadingSubmit && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditing ? 'Atualizar' : 'Criar'} Usuário
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate('..')}
                className="flex-1"
              >
                Cancelar
              </Button>
            </PageActions>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}

export default UsuarioFormPage;
