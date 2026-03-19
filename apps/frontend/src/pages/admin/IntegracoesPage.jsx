import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Link2, ShoppingBag, Activity, GitBranch } from 'lucide-react';
import IntegrationsStatus from './IntegrationsStatus';
import Marketplace from '@/components/marketplace/Marketplace';
import QueueMonitor from '@/components/admin/QueueMonitor';
import IntegracoesConfigPage from './configuracoes/IntegracoesConfigPage';

export default function IntegracoesPage() {
  const [activeTab, setActiveTab] = useState("status");

  return (
    <div className="container mx-auto py-8 space-y-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">Conectividade e Integrações</h1>
        <p className="text-muted-foreground">Gerencie conexões com marketplaces, tokens de acesso, webhooks e vínculos de canais.</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid w-full grid-cols-4 max-w-2xl">
          <TabsTrigger value="status" className="flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            Status
          </TabsTrigger>
          <TabsTrigger value="marketplace" className="flex items-center gap-2">
            <ShoppingBag className="h-4 w-4" />
            Marketplace
          </TabsTrigger>
          <TabsTrigger value="webhooks" className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Webhooks
          </TabsTrigger>
          <TabsTrigger value="vinculos" className="flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Vínculos de Canais
          </TabsTrigger>
        </TabsList>

        <TabsContent value="status" className="space-y-4 border-none p-0 outline-none">
          <IntegrationsStatus onAddClick={() => setActiveTab("marketplace")} />
        </TabsContent>

        <TabsContent value="marketplace" className="space-y-4 border-none p-0 outline-none">
          <Marketplace />
        </TabsContent>

        <TabsContent value="webhooks" className="space-y-4 border-none p-0 outline-none">
          <QueueMonitor />
        </TabsContent>

        <TabsContent value="vinculos" className="space-y-4 border-none p-0 outline-none">
          <IntegracoesConfigPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
