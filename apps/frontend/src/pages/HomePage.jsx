import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import {
  ArrowRightIcon,
  Boxes,
  TrendingUp,
  Warehouse,
  ShoppingCart,
} from 'lucide-react';

function HomePage() {
  const quickActions = [
    {
      title: 'Produtos',
      href: '/produtos',
      icon: Boxes,
      description: 'Gerencie seu catálogo',
      color: 'text-brand-aqua',
      bgColor: 'bg-brand-aqua-soft'
    },
    {
      title: 'Vendas',
      href: '/vendas',
      icon: ShoppingCart,
      description: 'Acompanhe os pedidos',
      color: 'text-brand-blue',
      bgColor: 'bg-brand-blue-soft'
    },
    {
      title: 'Estoque',
      href: '/estoque',
      icon: Warehouse,
      description: 'Controle de inventário',
      color: 'text-amber-700',
      bgColor: 'bg-brand-yellow-soft'
    },
    {
      title: 'Produção',
      href: '/producao',
      icon: TrendingUp,
      description: 'Painel operacional',
      color: 'text-brand-pink',
      bgColor: 'bg-brand-pink-soft'
    }
  ];

  return (
    <div className="container mx-auto py-8 px-4 md:px-6 max-w-6xl">
      {/* Welcome Section */}
      <div className="mb-8">
        <h1 className="page-title">
          Bem-vindo(a) ao Nisti Print!
        </h1>
        <p className="text-lg text-muted-foreground mt-2 max-w-2xl">
          Sua plataforma completa para gerenciamento de vendas e produção.
          Tudo o que você precisa em um só lugar.
        </p>
      </div>

      {/* Quick Actions Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {quickActions.map((action, index) => {
          const Icon = action.icon;
          return (
            <Link key={index} to={action.href}>
              <Card className="group h-full border-border/80 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
                <CardHeader className="pb-3">
                  <div
                    className={`w-12 h-12 rounded-xl ${action.bgColor} flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-300`}
                  >
                    <Icon className={`h-6 w-6 ${action.color}`} />
                  </div>
                  <CardTitle className="text-lg">{action.title}</CardTitle>
                  <CardDescription className="text-sm">
                    {action.description}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center text-sm font-semibold text-primary">
                    Acessar
                    <ArrowRightIcon className="h-4 w-4 ml-1 group-hover:translate-x-1 transition-transform" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

    </div>
  );
}

export default HomePage;
