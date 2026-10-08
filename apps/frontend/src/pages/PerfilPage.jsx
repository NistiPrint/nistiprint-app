import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/ui/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/contexts/AuthContext';
import UserService from '@/services/UserService';
import { LockKeyhole, User } from 'lucide-react';
import { toast } from 'sonner';

function PerfilPage() {
  const { user, refreshCurrentUser } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [nome, setNome] = useState(user?.nome || '');
  const [senhaAtual, setSenhaAtual] = useState('');
  const [novaSenha, setNovaSenha] = useState('');
  const [confirmacao, setConfirmacao] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const forcedPasswordChange = Boolean(user?.must_change_password) || searchParams.get('trocar-senha') === '1';

  useEffect(() => setNome(user?.nome || ''), [user?.nome]);

  const saveName = async (event) => {
    event.preventDefault();
    setSavingName(true);
    try {
      await UserService.updateProfile({ nome });
      await refreshCurrentUser();
      toast.success('Nome atualizado.');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível atualizar o nome.');
    } finally {
      setSavingName(false);
    }
  };

  const savePassword = async (event) => {
    event.preventDefault();
    if (novaSenha.length < 8) return toast.error('A nova senha deve ter ao menos 8 caracteres.');
    if (novaSenha !== confirmacao) return toast.error('As senhas não conferem.');
    setSavingPassword(true);
    try {
      await UserService.changePassword({ senha_atual: senhaAtual, nova_senha: novaSenha });
      await refreshCurrentUser();
      navigate('/perfil', { replace: true });
      setSenhaAtual('');
      setNovaSenha('');
      setConfirmacao('');
      toast.success('Senha atualizada.');
    } catch (error) {
      toast.error(error.response?.data?.error || 'Não foi possível atualizar a senha.');
    } finally {
      setSavingPassword(false);
    }
  };

  const grantedModules = Object.entries(user?.permissoes || {})
    .filter(([, actions]) => Object.values(actions || {}).some(Boolean))
    .map(([resource]) => resource);
  const demandAccess = user?.permissoes_demanda;

  return (
    <div className="container mx-auto space-y-6 py-6">
      <PageHeader title="Meu Perfil" icon={User} description="Atualize seu nome e senha e consulte seu acesso ao sistema." />

      {forcedPasswordChange && (
        <div role="alert" className="rounded-lg border border-warning/40 bg-warning-soft p-4 text-sm font-medium text-warning">
          Troque sua senha inicial para continuar usando o sistema.
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Informações pessoais</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <form onSubmit={saveName} className="space-y-2">
              <Label htmlFor="profile-name">Nome</Label>
              <div className="flex gap-2">
                <Input id="profile-name" value={nome} maxLength={100} onChange={(event) => setNome(event.target.value)} required />
                <Button type="submit" disabled={savingName || nome.trim() === user?.nome}>{savingName ? 'Salvando…' : 'Salvar'}</Button>
              </div>
            </form>
            <div className="grid gap-1"><span className="text-sm font-medium text-muted-foreground">E-mail</span><span>{user?.email || 'Não informado'}</span></div>
            <div className="grid gap-1"><span className="text-sm font-medium text-muted-foreground">Setor</span><span className="font-semibold text-primary">{user?.setor_nome || 'Sem setor'}</span></div>
            <div className="grid gap-1"><span className="text-sm font-medium text-muted-foreground">Perfil</span><span>{user?.is_admin ? 'Administrador' : 'Usuário'}</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><LockKeyhole className="h-4 w-4" />Segurança e acesso</CardTitle>
            <CardDescription>Altere sua senha e consulte os módulos disponíveis.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <form onSubmit={savePassword} className="space-y-3">
              <div className="space-y-1"><Label htmlFor="current-password">Senha atual</Label><Input id="current-password" type="password" autoComplete="current-password" value={senhaAtual} onChange={(event) => setSenhaAtual(event.target.value)} required /></div>
              <div className="space-y-1"><Label htmlFor="new-password">Nova senha</Label><Input id="new-password" type="password" autoComplete="new-password" minLength={8} value={novaSenha} onChange={(event) => setNovaSenha(event.target.value)} required /></div>
              <div className="space-y-1"><Label htmlFor="confirm-password">Confirmar nova senha</Label><Input id="confirm-password" type="password" autoComplete="new-password" minLength={8} value={confirmacao} onChange={(event) => setConfirmacao(event.target.value)} required /></div>
              <Button type="submit" disabled={savingPassword}>{savingPassword ? 'Atualizando…' : 'Atualizar senha'}</Button>
            </form>
            <div className="border-t pt-4">
              <p className="text-sm font-medium">Acessos liberados</p>
              {user?.is_admin ? <p className="mt-1 text-sm text-muted-foreground">Acesso administrativo completo.</p> : (
                <div className="mt-2 space-y-1 text-sm text-muted-foreground">
                  <p>{grantedModules.length ? grantedModules.join(', ') : 'Nenhum módulo adicional concedido.'}</p>
                  {demandAccess?.fields?.length > 0 && <p>Campos de demanda: {demandAccess.fields.length}</p>}
                  {demandAccess?.actions?.length > 0 && <p>Ações de demanda: {demandAccess.actions.length}</p>}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default PerfilPage;
