import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Link2, ShoppingBag, HelpCircle } from 'lucide-react';
import IntegrationsStatus from './IntegrationsStatus';
import Marketplace from '@/components/marketplace/Marketplace';

export default function IntegracoesPage() {
  const [activeTab, setActiveTab] = useState("integracoes");

  return (
    <TooltipProvider>
      <div className="container mx-auto py-8 space-y-6">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold tracking-tight">Conectividade e Integrações</h1>
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle className="h-5 w-5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent className="max-w-lg">
                <p className="text-sm font-medium">Gerencie todas as suas integrações em um só lugar</p>
                <ul className="text-xs mt-2 space-y-1">
                  <li>• <strong>Integrações:</strong> Contas conectadas (Bling, Shopee, Amazon, etc.)</li>
                  <li>• <strong>Marketplace:</strong> Catálogo de plataformas disponíveis para instalar</li>
                  <li>• <strong>Canais e Lojas:</strong> Vínculos entre canais de venda e lojas no Bling</li>
                </ul>
              </TooltipContent>
            </Tooltip>
          </div>
          <p className="text-muted-foreground">Configure e gerencie as conexões do seu sistema com plataformas externas.</p>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="grid w-full grid-cols-2 max-w-xl">
            <TabsTrigger value="integracoes" className="flex items-center gap-2">
              <Link2 className="h-4 w-4" />
              Integrações
              <Tooltip>
                <TooltipTrigger className="ml-1">
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Contas já instaladas e configuradas</p>
                </TooltipContent>
              </Tooltip>
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="flex items-center gap-2">
              <ShoppingBag className="h-4 w-4" />
              Marketplace
              <Tooltip>
                <TooltipTrigger className="ml-1">
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Catálogo de plataformas para instalar</p>
                </TooltipContent>
              </Tooltip>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="integracoes" className="space-y-4 border-none p-0 outline-none">
            <IntegrationsStatus onAddClick={() => setActiveTab("marketplace")} />
          </TabsContent>

          <TabsContent value="marketplace" className="space-y-4 border-none p-0 outline-none">
            <Marketplace />
          </TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  );
}
