import React from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  ArrowRightIcon,
  Boxes,
  TrendingUp,
  Warehouse,
  ShoppingCart,
  BarChart3,
  CheckCircle2,
  Clock
} from 'lucide-react';

function HomePage() {
  const quickActions = [
    {
      title: 'Produtos',
      href: '/produtos',
      icon: Boxes,
      description: 'Gerencie seu catálogo',
      color: 'from-blue-500 to-blue-600',
      bgColor: 'bg-blue-50'
    },
    {
      title: 'Vendas',
      href: '/vendas',
      icon: ShoppingCart,
      description: 'Acompanhe os pedidos',
      color: 'from-green-500 to-green-600',
      bgColor: 'bg-green-50'
    },
    {
      title: 'Estoque',
      href: '/estoque',
      icon: Warehouse,
      description: 'Controle de inventário',
      color: 'from-orange-500 to-orange-600',
      bgColor: 'bg-orange-50'
    },
    {
      title: 'Produção',
      href: '/producao',
      icon: TrendingUp,
      description: 'Painel operacional',
      color: 'from-purple-500 to-purple-600',
      bgColor: 'bg-purple-50'
    }
  ];

  const stats = [
    {
      label: 'Status do Sistema',
      value: 'Operacional',
      icon: CheckCircle2,
      color: 'text-green-600',
      bgColor: 'bg-green-50'
    },
    {
      label: 'Última Atualização',
      value: new Date().toLocaleDateString('pt-BR'),
      icon: Clock,
      color: 'text-blue-600',
      bgColor: 'bg-blue-50'
    }
  ];

  return (
    <div className="container mx-auto py-8 px-4 md:px-6 max-w-6xl">
      {/* Welcome Section */}
      <div className="mb-8">
        <h1 className="text-3xl md:text-4xl font-bold tracking-tight bg-gradient-to-r from-primary to-primary/70 bg-clip-text text-transparent">
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
              <Card className="group hover:shadow-lg transition-all duration-300 hover:-translate-y-1 border-muted/50 h-full">
                <CardHeader className="pb-3">
                  <div
                    className={`w-12 h-12 rounded-xl ${action.bgColor} flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-300`}
                  >
                    <Icon className={`h-6 w-6 ${action.color.replace('from-', 'text-').split(' ')[0]}`} />
                  </div>
                  <CardTitle className="text-lg">{action.title}</CardTitle>
                  <CardDescription className="text-sm">
                    {action.description}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center text-sm font-medium text-primary opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                    Acessar
                    <ArrowRightIcon className="h-4 w-4 ml-1 group-hover:translate-x-1 transition-transform" />
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      {/* Info Section */}
      <Card className="border-muted/50 shadow-sm">
        <CardHeader>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-xl">Visão Geral</CardTitle>
          </div>
          <CardDescription>
            Navegue pelos módulos para gerenciar seus produtos, estoque, vendas e muito mais.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {stats.map((stat, index) => {
              const Icon = stat.icon;
              return (
                <div
                  key={index}
                  className="flex items-center gap-3 p-4 rounded-lg bg-muted/30 border border-muted"
                >
                  <div
                    className={`w-10 h-10 rounded-lg ${stat.bgColor} flex items-center justify-center`}
                  >
                    <Icon className={`h-5 w-5 ${stat.color}`} />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">{stat.label}</p>
                    <p className="text-base font-semibold">{stat.value}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Future metrics placeholder */}
          <div className="mt-6 p-4 rounded-lg border border-dashed border-muted bg-muted/20">
            <p className="text-sm text-muted-foreground text-center">
              📊 Métricas em tempo real serão exibidas aqui em breve
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default HomePage;
