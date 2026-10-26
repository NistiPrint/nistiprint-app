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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import PageHeader from '@/components/ui/PageHeader';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import UserService from '@/services/UserService';
import { Edit, KeyRound, PlusCircle, RotateCcw, Trash2, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

function UsuarioListPage() {
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [passwordDialogUser, setPasswordDialogUser] = useState(null);
  const [passwordDialogMode, setPasswordDialogMode] = useState('reset');
  const [initialPassword, setInitialPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [savingPassword, setSavingPassword] = useState(false);
  const [userStatusFilter, setUserStatusFilter] = useState('active');
  const [searchParams] = useSearchParams();
  const isPendingAccessView = searchParams.get('status') === 'pendente';
  const activeUserCount = usuarios.filter((usuario) => usuario.ativo).length;
  const inactiveUserCount = usuarios.length - activeUserCount;
  const filteredUsers = useMemo(() => {
    if (isPendingAccessView) {
      return usuarios.filter((usuario) => usuario.ativo && usuario.access_status === 'pending');
    }
    if (userStatusFilter === 'inactive') return usuarios.filter((usuario) => !usuario.ativo);
    if (userStatusFilter === 'all') return usuarios;
    return usuarios.filter((usuario) => usuario.ativo);
  }, [usuarios, isPendingAccessView, userStatusFilter]);

  useEffect(() => {
    fetchUsuarios();
  }, []);

  const fetchUsuarios = async () => {
    try {
      const data = await UserService.getAll();
      setUsuarios(data);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Erro ao carregar usuários');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await UserService.delete(id);
      toast.success('Usuário desativado com sucesso.');
      await fetchUsuarios();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível desativar o usuário.');
    }
  };

  const handleProvisionAccess = async (usuario) => {
    setPasswordDialogUser(usuario);
    setPasswordDialogMode('reset');
    setInitialPassword('');
    setPasswordConfirmation('');
  };

  const handleReactivate = (usuario) => {
    setPasswordDialogUser(usuario);
    setPasswordDialogMode('reactivate');
    setInitialPassword('');
    setPasswordConfirmation('');
  };

  const submitAccessChange = async (event) => {
    event.preventDefault();
    if (initialPassword.length < 8) {
      toast.error('A senha temporária deve ter ao menos 8 caracteres.');
      return;
    }
    if (initialPassword !== passwordConfirmation) {
      toast.error('As senhas não conferem.');
      return;
    }
    if (!passwordDialogUser) return;
    setSavingPassword(true);
    try {
      if (passwordDialogMode === 'reactivate') {
        await UserService.reactivate(passwordDialogUser.id, initialPassword);
        toast.success('Usuário reativado. Ele deverá trocar a senha no próximo acesso.');
      } else {
        await UserService.provisionAccess(passwordDialogUser.id, initialPassword);
        toast.success('Senha redefinida. O usuário deverá trocá-la no próximo acesso.');
      }
      await fetchUsuarios();
      setPasswordDialogUser(null);
      setInitialPassword('');
      setPasswordConfirmation('');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível atualizar o acesso.');
    } finally {
      setSavingPassword(false);
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
          {!isPendingAccessView && (
            <div role="group" aria-label="Filtrar usuários por status" className="mb-4 flex flex-wrap gap-2">
              <Button variant={userStatusFilter === 'active' ? 'default' : 'outline'} size="sm" onClick={() => setUserStatusFilter('active')}>
                Ativos ({activeUserCount})
              </Button>
              <Button variant={userStatusFilter === 'inactive' ? 'default' : 'outline'} size="sm" onClick={() => setUserStatusFilter('inactive')}>
                Desativados ({inactiveUserCount})
              </Button>
              <Button variant={userStatusFilter === 'all' ? 'default' : 'outline'} size="sm" onClick={() => setUserStatusFilter('all')}>
                Todos ({usuarios.length})
              </Button>
            </div>
          )}
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
                    <Badge variant={usuario.access_status === 'ready' ? 'success' : usuario.access_status === 'password_change_required' ? 'info' : 'outline'}>
                      {usuario.access_status === 'password_change_required'
                        ? 'Troca obrigatória'
                        : usuario.access_status === 'pending' ? 'Acesso pendente' : 'Configurado'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={usuario.is_admin ? 'destructive' : 'outline'}>
                      {usuario.is_admin ? 'Admin' : 'Usuário'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="outline" size="sm" aria-label={`Editar ${usuario.nome}`} asChild>
                              <Link to={`${usuario.id}/editar`}>
                                <Edit className="h-4 w-4" />
                              </Link>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Editar dados de {usuario.nome}</TooltipContent>
                        </Tooltip>
                      {usuario.ativo && usuario.email.toLowerCase() !== 'admin@admin.com' && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="outline" size="sm" aria-label={`Redefinir senha de ${usuario.nome}`} onClick={() => handleProvisionAccess(usuario)}>
                              <KeyRound className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{usuario.access_status === 'pending' ? 'Regularizar acesso' : 'Redefinir senha'}</TooltipContent>
                        </Tooltip>
                      )}
                      {!usuario.ativo && usuario.email.toLowerCase() !== 'admin@admin.com' && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="outline" size="sm" aria-label={`Reativar ${usuario.nome}`} onClick={() => handleReactivate(usuario)}>
                              <RotateCcw className="h-4 w-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Reativar {usuario.nome}</TooltipContent>
                        </Tooltip>
                      )}
                      {usuario.ativo && usuario.email.toLowerCase() !== 'admin@admin.com' && <AlertDialog>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <AlertDialogTrigger asChild>
                              <Button variant="outline" size="sm" aria-label={`Desativar ${usuario.nome}`}>
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </AlertDialogTrigger>
                          </TooltipTrigger>
                          <TooltipContent>Desativar {usuario.nome}</TooltipContent>
                        </Tooltip>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Confirmar desativação</AlertDialogTitle>
                            <AlertDialogDescription>
                              Deseja desativar "{usuario.nome}"? O usuário perderá o acesso e poderá ser reativado por um administrador.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction
                              onClick={() => handleDelete(usuario.id)}
                              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                            >
                              Desativar
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>}
                      </TooltipProvider>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {filteredUsers.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              {isPendingAccessView
                ? 'Nenhum usuário com acesso pendente.'
                : userStatusFilter === 'inactive' ? 'Nenhum usuário desativado.'
                  : userStatusFilter === 'active' ? 'Nenhum usuário ativo.' : 'Nenhum usuário cadastrado.'}
            </div>
          )}
        </CardContent>
      </Card>
      <Dialog open={Boolean(passwordDialogUser)} onOpenChange={(open) => {
        if (!open && !savingPassword) {
          setPasswordDialogUser(null);
          setInitialPassword('');
          setPasswordConfirmation('');
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{passwordDialogMode === 'reactivate' ? 'Reativar usuário' : 'Redefinir senha'}</DialogTitle>
            <DialogDescription>
              {passwordDialogMode === 'reactivate'
                ? `Defina uma senha temporária para ${passwordDialogUser?.nome}. A conta exigirá troca de senha no próximo acesso.`
                : `Defina uma senha temporária para ${passwordDialogUser?.nome}. Ele deverá trocá-la no próximo acesso.`}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submitAccessChange} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="temporary-password" className="text-sm font-medium">Senha temporária</label>
              <Input id="temporary-password" type="password" autoComplete="new-password" minLength={8} value={initialPassword} onChange={(event) => setInitialPassword(event.target.value)} required />
            </div>
            <div className="space-y-2">
              <label htmlFor="confirm-temporary-password" className="text-sm font-medium">Confirmar senha</label>
              <Input id="confirm-temporary-password" type="password" autoComplete="new-password" minLength={8} value={passwordConfirmation} onChange={(event) => setPasswordConfirmation(event.target.value)} required />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" disabled={savingPassword} onClick={() => setPasswordDialogUser(null)}>Cancelar</Button>
              <Button type="submit" disabled={savingPassword || initialPassword.length < 8 || initialPassword !== passwordConfirmation}>
                {savingPassword ? 'Salvando…' : passwordDialogMode === 'reactivate' ? 'Reativar usuário' : 'Redefinir senha'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default UsuarioListPage;
