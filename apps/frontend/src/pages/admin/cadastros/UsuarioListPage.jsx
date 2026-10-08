import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import PageHeader from '@/components/ui/PageHeader';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import UserService from '@/services/UserService';
import { Edit, KeyRound, PlusCircle, Trash2, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

function UsuarioListPage() {
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchParams] = useSearchParams();
  const filteredUsers = useMemo(() => searchParams.get('status') === 'pendente'
    ? usuarios.filter((usuario) => usuario.ativo && !usuario.auth_user_id)
    : usuarios, [usuarios, searchParams]);

  useEffect(() => {
    fetchUsuarios();
  }, []);

  const fetchUsuarios = async () => {
    try {
      const data = await UserService.getAll();
      setUsuarios(data);
    } catch (error) {
      toast.error('Erro ao carregar usuários');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await UserService.delete(id);
      toast.success('Usuário deletado com sucesso');
      fetchUsuarios(); // Refresh the list
    } catch (error) {
      toast.error('Erro ao deletar usuário');
    }
  };

  const handleProvisionAccess = async (usuario) => {
    const password = window.prompt(`Defina uma senha inicial para ${usuario.nome} (mínimo 8 caracteres):`);
    if (!password) return;
    if (password.length < 8) {
      toast.error('A senha inicial deve ter ao menos 8 caracteres.');
      return;
    }
    try {
      await UserService.provisionAccess(usuario.id, password);
      toast.success('Acesso regularizado. O usuário trocará a senha no próximo login.');
      await fetchUsuarios();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível regularizar o acesso.');
    }
  };

  if (loading) {
    return <div className="text-center py-4">Carregando usuários...</div>;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Usuários"
        icon={Users}
        actions={
          <Button asChild>
            <Link to="novo">
              <PlusCircle className="mr-2 h-4 w-4" />
              Novo Usuário
            </Link>
          </Button>
        }
      />
      <Card>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nome</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Setor</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Acesso</TableHead>
                <TableHead>Admin</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredUsers.map((usuario) => (
                <TableRow key={usuario.id}>
                  <TableCell className="font-medium">{usuario.nome}</TableCell>
                  <TableCell>{usuario.email}</TableCell>
                  <TableCell>{usuario.setor_nome || 'N/A'}</TableCell>
                  <TableCell>
                    <Badge variant={usuario.ativo ? 'default' : 'secondary'}>
                      {usuario.ativo ? 'Ativo' : 'Inativo'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={usuario.auth_user_id ? (usuario.must_change_password ? 'info' : 'success') : 'outline'}>
                      {usuario.auth_user_id ? (usuario.must_change_password ? 'Troca obrigatória' : 'Configurado') : 'Acesso pendente'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={usuario.is_admin ? 'destructive' : 'outline'}>
                      {usuario.is_admin ? 'Admin' : 'Usuário'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link to={`${usuario.id}/editar`}>
                          <Edit className="h-4 w-4" />
                        </Link>
                      </Button>
                      {usuario.ativo && usuario.email.toLowerCase() !== 'admin@admin.com' && (
                        <Button variant="outline" size="sm" aria-label={`${usuario.auth_user_id ? 'Redefinir senha de' : 'Regularizar acesso de'} ${usuario.nome}`} onClick={() => handleProvisionAccess(usuario)}>
                          <KeyRound className="h-4 w-4" />
                        </Button>
                      )}
                      {usuario.email.toLowerCase() !== 'admin@admin.com' && <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="outline" size="sm">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Confirmar exclusão</AlertDialogTitle>
                            <AlertDialogDescription>
                              Tem certeza que deseja deletar o usuário "{usuario.nome}"?
                              Esta ação não pode ser desfeita.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() => handleDelete(usuario.id)}
                              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                              Deletar
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {filteredUsers.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              {searchParams.get('status') === 'pendente' ? 'Nenhum usuário com acesso pendente.' : 'Nenhum usuário cadastrado.'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default UsuarioListPage;
