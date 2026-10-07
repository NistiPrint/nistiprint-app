import { useEffect } from 'react';
import { Outlet, useLocation, useSearchParams } from 'react-router-dom';
import { HelpCircle, KeyRound, Link2, Settings2, ShoppingBag, Store } from 'lucide-react';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import Marketplace from '@/components/marketplace/Marketplace';

import IntegrationAppProfilesPage from './IntegrationAppProfilesPage';
import IntegrationsStatus from './IntegrationsStatus';
import IntegrationRoutingPage from './configuracoes/IntegrationRoutingPage';
import ConfiguracoesBlingPage from './configuracoes/ConfiguracoesBlingPage';
import { Link } from 'react-router-dom';
import { CardDescription, CardTitle } from '@/components/ui/card';

const ABAS_VALIDAS = ['integracoes', 'marketplace', 'oauth-apps', 'regras-erp'];

export default function IntegracoesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  // A aba vem da URL quando informada. Sem isso, o link da torre de despacho
  // ("canal sem regra cadastrada") abre esta pagina na primeira aba e o
  // operador tem que descobrir sozinho onde e o cadastro — que e exatamente o
  // atrito que o link existe para remover.
  const requestedTab = searchParams.get('aba');
  const activeTab = ABAS_VALIDAS.includes(requestedTab)
    ? requestedTab
    : 'integracoes';
  const location = useLocation();
  const isInstallRoute = location.pathname.includes('/configuracoes/integracoes/install/');

  useEffect(() => {
    if (!isInstallRoute && (!requestedTab || !ABAS_VALIDAS.includes(requestedTab))) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set('aba', 'integracoes');
        return next;
      }, { replace: true });
    }
  }, [requestedTab, isInstallRoute, setSearchParams]);

  const changeTab = (value) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set('aba', value);
    return next;
  });

  if (isInstallRoute) {
    return (
      <div className="container mx-auto py-8">
        <Outlet />
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="space-y-6">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold tracking-tight">Conectividade e Integracoes</h1>
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle className="h-5 w-5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent className="max-w-lg">
                <p className="text-sm font-medium">Gerencie todas as integrações em um só lugar.</p>
                <ul className="mt-2 space-y-1 text-xs">
                  <li>- Integracoes: contas conectadas.</li>
                  <li>- Marketplace: catalogo de plataformas disponiveis.</li>
                  <li>- Apps OAuth: aplicativos e callbacks por provedor.</li>
                  <li>- Regras ERP: roteamento e conta Bling padrão.</li>
                </ul>
              </TooltipContent>
            </Tooltip>
          </div>
          <p className="text-muted-foreground">
            Configure conexoes, autorizacoes OAuth e o roteamento operacional das integracoes.
          </p>
        </div>

        <Tabs value={activeTab} onValueChange={changeTab} className="space-y-6">
          <TabsList className="grid w-full max-w-4xl grid-cols-2 sm:grid-cols-4">
            <TabsTrigger value="integracoes" className="flex items-center gap-2">
              <Link2 className="h-4 w-4" />
              Integracoes
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="flex items-center gap-2">
              <ShoppingBag className="h-4 w-4" />
              Marketplace
            </TabsTrigger>
            <TabsTrigger value="oauth-apps" className="flex items-center gap-2">
              <KeyRound className="h-4 w-4" />
              Apps OAuth
            </TabsTrigger>
            <TabsTrigger value="regras-erp" className="flex items-center gap-2"><Settings2 className="h-4 w-4" />Regras ERP</TabsTrigger>
          </TabsList>

          <TabsContent value="integracoes" className="space-y-4 border-none p-0 outline-none">
            <IntegrationsStatus onAddClick={() => changeTab('marketplace')} />
            <details className="rounded-xl border bg-card">
              <summary className="flex cursor-pointer list-none items-center gap-2 p-4 font-medium"><Store className="h-4 w-4" />Cadastros avançados</summary>
              <div className="grid gap-3 border-t p-4 sm:grid-cols-2">
                <Link to="/cadastros/plataforma" className="rounded-lg border p-4 hover:bg-muted"><CardTitle className="text-base">Plataformas</CardTitle><CardDescription className="mt-1">Gerenciar os marketplaces cadastrados.</CardDescription></Link>
                <Link to="/cadastros/canal-venda" className="rounded-lg border p-4 hover:bg-muted"><CardTitle className="text-base">Canais de venda</CardTitle><CardDescription className="mt-1">Gerenciar canais e associações às plataformas.</CardDescription></Link>
              </div>
            </details>
          </TabsContent>

          <TabsContent value="marketplace" className="space-y-4 border-none p-0 outline-none">
            <Marketplace />
          </TabsContent>


          <TabsContent value="oauth-apps" className="space-y-4 border-none p-0 outline-none">
            <IntegrationAppProfilesPage />
          </TabsContent>
          <TabsContent value="regras-erp" className="space-y-6 border-none p-0 outline-none">
            <section><h2 className="mb-3 text-xl font-semibold">Roteamento de contas</h2><IntegrationRoutingPage /></section>
            <section className="border-t pt-6"><h2 className="mb-3 text-xl font-semibold">Conta Bling padrão</h2><ConfiguracoesBlingPage /></section>
          </TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  );
}
