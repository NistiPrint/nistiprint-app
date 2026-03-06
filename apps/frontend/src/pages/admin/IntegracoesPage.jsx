import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Link2, ShoppingBag, Activity } from 'lucide-react';
import IntegrationsStatus from './IntegrationsStatus';
import Marketplace from '@/components/marketplace/Marketplace';
import WebhookMonitor from '@/components/marketplace/WebhookMonitor';

export default function IntegracoesPage() {
  const [activeTab, setActiveTab] = useState("status");

  return (
    <div className="container mx-auto py-8 space-y-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight">Conectividade e Integrações</h1>
        <p className="text-muted-foreground">Gerencie conexões com marketplaces, tokens de acesso e monitoramento de webhooks.</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid w-full grid-cols-3 max-w-md">
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
        </TabsList>

        <TabsContent value="status" className="space-y-4 border-none p-0 outline-none">
          <IntegrationsStatus onAddClick={() => setActiveTab("marketplace")} />
        </TabsContent>

        <TabsContent value="marketplace" className="space-y-4 border-none p-0 outline-none">
          <Marketplace />
        </TabsContent>

        <TabsContent value="webhooks" className="space-y-4 border-none p-0 outline-none">
          <WebhookMonitor />
        </TabsContent>
      </Tabs>
    </div>
  );
}
