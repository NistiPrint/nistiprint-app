import React from 'react';
import PageHeader from '@/components/ui/PageHeader';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { User } from 'lucide-react';

function PerfilPage() {
  const { user } = useAuth();

  return (
    <div className="container mx-auto py-6">
      <PageHeader 
        title="Meu Perfil" 
        icon={User} 
        description="Gerencie suas informações pessoais e configurações de conta."
      />
      
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Informações Pessoais</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-1">
              <span className="text-sm font-medium text-muted-foreground">Nome</span>
              <span className="text-base">{user?.nome || 'Não informado'}</span>
            </div>
            <div className="grid gap-1">
              <span className="text-sm font-medium text-muted-foreground">E-mail</span>
              <span className="text-base">{user?.email || 'Não informado'}</span>
            </div>
            <div className="grid gap-1">
              <span className="text-sm font-medium text-muted-foreground">Setor</span>
              <span className="text-base font-semibold text-primary">{user?.setor_nome || 'Sem Setor'}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Configurações de Segurança</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Funcionalidades de alteração de senha e autenticação em duas etapas estarão disponíveis em breve.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default PerfilPage;
