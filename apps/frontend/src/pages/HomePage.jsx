import React from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ArrowRightIcon } from 'lucide-react';

function HomePage() {
  return (
    <div className="container mx-auto py-8">
      <Card className="text-center">
        <CardHeader>
          <CardTitle className="text-4xl font-bold">Bem-vindo(a) ao Nisti Print!</CardTitle>
          <CardDescription className="text-lg text-muted-foreground">
            Sua plataforma completa para gerenciamento de vendas e produção.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-md leading-relaxed">
            Navegue pelos módulos para gerenciar seus produtos, estoque, vendas,
            e muito mais, tudo com uma interface moderna e eficiente.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Link to="/produtos">
              <Button size="lg" className="flex items-center gap-2">
                Gerenciar Produtos <ArrowRightIcon className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/vendas">
              <Button size="lg" variant="outline" className="flex items-center gap-2">
                Visualizar Vendas <ArrowRightIcon className="h-4 w-4" />
              </Button>
            </Link>
            <Link to="/estoque">
              <Button size="lg" variant="outline" className="flex items-center gap-2">
                Controlar Estoque <ArrowRightIcon className="h-4 w-4" />
              </Button>
            </Link>
          </div>
          <div className="mt-8 text-sm text-gray-500">
            {/* Placeholder for future status/metrics */}
            <p>Status do sistema: Operacional</p>
            <p>Última atualização: {new Date().toLocaleDateString()}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default HomePage;
