import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { CalendarClock, HelpCircle, KeyRound, Link2, ShoppingBag } from 'lucide-react';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import Marketplace from '@/components/marketplace/Marketplace';

import IntegrationAppProfilesPage from './IntegrationAppProfilesPage';
import IntegrationsStatus from './IntegrationsStatus';
import LogisticaIntegracaoPage from './configuracoes/LogisticaIntegracaoPage';

export default function IntegracoesPage() {
  const [activeTab, setActiveTab] = useState('integracoes');
  const location = useLocation();
  const isInstallRoute = location.pathname.includes('/configuracoes/integracoes/install/');

  if (isInstallRoute) {
    return (
      <div className="container mx-auto py-8">
        <Outlet />
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="container mx-auto space-y-6 py-8">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold tracking-tight">Conectividade e Integracoes</h1>
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle className="h-5 w-5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent className="max-w-lg">
                <p className="text-sm font-medium">Gerencie todas as integracoes em um so lugar.</p>
                <ul className="mt-2 space-y-1 text-xs">
                  <li>- Integracoes: contas conectadas.</li>
                  <li>- Marketplace: catalogo de plataformas disponiveis.</li>
                  <li>- Logistica: vinculos entre canais e lojas do Bling.</li>
                  <li>- Apps OAuth: aplicativos e callbacks por provedor.</li>
                </ul>
              </TooltipContent>
            </Tooltip>
          </div>
          <p className="text-muted-foreground">
            Configure conexoes, autorizacoes OAuth e o roteamento operacional das integracoes.
          </p>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="grid w-full max-w-4xl grid-cols-4">
            <TabsTrigger value="integracoes" className="flex items-center gap-2">
              <Link2 className="h-4 w-4" />
              Integracoes
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="flex items-center gap-2">
              <ShoppingBag className="h-4 w-4" />
              Marketplace
            </TabsTrigger>
            <TabsTrigger value="logistica" className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4" />
              Logistica
            </TabsTrigger>
            <TabsTrigger value="oauth-apps" className="flex items-center gap-2">
              <KeyRound className="h-4 w-4" />
              Apps OAuth
            </TabsTrigger>
          </TabsList>

          <TabsContent value="integracoes" className="space-y-4 border-none p-0 outline-none">
            <IntegrationsStatus onAddClick={() => setActiveTab('marketplace')} />
          </TabsContent>

          <TabsContent value="marketplace" className="space-y-4 border-none p-0 outline-none">
            <Marketplace />
          </TabsContent>

          <TabsContent value="logistica" className="space-y-4 border-none p-0 outline-none">
            <LogisticaIntegracaoPage />
          </TabsContent>

          <TabsContent value="oauth-apps" className="space-y-4 border-none p-0 outline-none">
            <IntegrationAppProfilesPage />
          </TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  );
}
