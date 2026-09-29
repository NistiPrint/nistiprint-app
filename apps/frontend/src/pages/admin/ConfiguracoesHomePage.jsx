import PageHeader from '@/components/ui/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/AuthContext';
import { SECOES } from '@/navigation';
import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function ConfiguracoesHomePage() {
  const { isAdmin, hasPermission } = useAuth();
  const secao = SECOES.find((item) => item.id === 'configuracoes');
  const grupos = (secao?.grupos || []).map((grupo) => ({
    ...grupo,
    itens: grupo.itens.filter((item) =>
      (!item.adminOnly || isAdmin()) &&
      (!item.permission || hasPermission(item.permission.a, item.permission.I))
    ),
  })).filter((grupo) => grupo.itens.length > 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Configurações" description="Escolha uma área para ajustar o funcionamento da aplicação." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {grupos.map((grupo) => (
          <Card key={grupo.nome} className="h-full border-border/90 shadow-sm transition-shadow hover:shadow-md">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg">{grupo.nome}</CardTitle>
              <CardDescription className="min-h-10 leading-5">{grupo.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1">
                {grupo.itens.map((item) => (
                  <li key={item.href}>
                    <Link to={item.href} className="group flex min-h-11 items-center justify-between gap-3 rounded-lg px-3 text-sm font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <span>{item.name}</span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                    </Link>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
