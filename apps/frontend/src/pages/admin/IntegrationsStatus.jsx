import LiveOrderConsultation from '@/components/marketplace/LiveOrderConsultation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import MarketplaceService from '@/services/MarketplaceService';
import { AlertCircle, CheckCircle2, Plus, RefreshCw, Trash2, Zap, Package, Building2, HelpCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function IntegrationsStatus({ onAddClick }) {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState(null);
  const [moduleFilter, setModuleFilter] = useState('all');

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      const data = await MarketplaceService.getInstalledIntegrations();
      if (data.success === false) {
        setIntegrations([]);
      } else {
        setIntegrations(data.installations || []);
      }
    } catch (error) {
      console.error(error);
      toast.error("Erro ao carregar integrações");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const handleTest = async (id) => {
    try {
      setTestingId(id);
      toast.info("Executando teste de conexão...");
      const data = await MarketplaceService.testIntegration(id);

      if (data.success) {
        const result = data.result;
        const isError = result.error || result.err_code || (result.message && result.message.includes("error"));

        if (!isError) {
          toast.success("Teste concluído: Conexão OK!");
        } else {
          toast.error(`Falha no teste: ${result.message || result.error || "Erro na API"}`);
        }
      }
    } catch (error) {
      const errorMsg = error.response?.data?.error || "Erro ao executar teste";
      toast.error(errorMsg);
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id, name) => {
    if (!confirm(`Tem certeza que deseja remover a integração "${name}"?`)) return;

    try {
      toast.info("Removendo integração...");
      await MarketplaceService.uninstallModule(id);
      toast.success("Integração removida com sucesso");
      fetchIntegrations();
    } catch (error) {
      toast.error("Erro ao remover integração");
    }
  };

  // Filtrar integrações por módulo
  const filteredIntegrations = moduleFilter === 'all' 
    ? integrations 
    : integrations.filter(i => {
        if (moduleFilter === 'bling') return i.module_id === 'bling';
        if (moduleFilter === 'marketplace') return i.module_id !== 'bling';
        return true;
      });

  // Contadores
  const totalBling = integrations.filter(i => i.module_id === 'bling').length;
  const totalMarketplace = integrations.filter(i => i.module_id !== 'bling').length;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold">Integrações Instaladas</h2>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle className="h-4 w-4 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent className="max-w-md">
                <p className="text-sm">
                  <strong>Integrações</strong> são conexões configuradas com plataformas externas.
                </p>
                <ul className="text-xs mt-2 space-y-1">
                  <li>• <strong>Bling (ERP):</strong> Gerencia pedidos, produtos e notas fiscais</li>
                  <li>• <strong>Marketplaces:</strong> Shopee, Amazon, Mercado Livre, etc.</li>
                </ul>
                <p className="text-xs mt-2 text-muted-foreground">
                  💡 Dica: Você precisa de pelo menos uma integração Bling e uma de marketplace para importar pedidos.
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <Button onClick={onAddClick} className="flex items-center gap-2">
          <Plus className="h-4 w-4" />
          Nova Integração
        </Button>
      </div>

      {/* Filtros por tipo de integração */}
      <Tabs value={moduleFilter} onValueChange={setModuleFilter} className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-3">
          <TabsTrigger value="all" className="flex items-center gap-2">
            <Package className="h-4 w-4" />
            Todas ({integrations.length})
          </TabsTrigger>
          <TabsTrigger value="bling" className="flex items-center gap-2">
            <Building2 className="h-4 w-4" />
            ERP (Bling) ({totalBling})
          </TabsTrigger>
          <TabsTrigger value="marketplace" className="flex items-center gap-2">
            <Package className="h-4 w-4" />
            Marketplaces ({totalMarketplace})
          </TabsTrigger>
        </TabsList>

        <div className="grid gap-6 mt-4">
          {loading ? (
            <div className="flex justify-center p-12">
              <RefreshCw className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : filteredIntegrations.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center flex flex-col items-center gap-4">
                <p className="text-muted-foreground">
                  {moduleFilter === 'bling' 
                    ? 'Nenhuma integração Bling encontrada.' 
                    : moduleFilter === 'marketplace'
                    ? 'Nenhuma integração de marketplace encontrada.'
                    : 'Nenhuma integração encontrada.'}
                </p>
                <Button onClick={onAddClick} variant="outline">
                  Adicionar Integração
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredIntegrations.map((item) => (
                <Card key={item.id} className="overflow-hidden border-t-4" style={{ borderTopColor: item.instance_color || '#64748b' }}>
                  <CardHeader className="bg-muted/30 pb-4">
                    <div className="flex justify-between items-start">
                      <div>
                        <Badge variant="outline" className="mb-2 uppercase text-[10px]" style={{ color: item.instance_color }}>
                          {item.module_id}
                        </Badge>
                        <CardTitle className="text-lg">{item.instance_name}</CardTitle>
                        {item.description && <p className="text-xs text-muted-foreground mt-1">{item.description}</p>}
                      </div>
                      <div className="flex gap-1">
                        {item.is_active ? (
                          <CheckCircle2 className="h-5 w-5 text-green-500" />
                        ) : (
                          <AlertCircle className="h-5 w-5 text-red-500" />
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-4 space-y-4">
                    <div className="text-xs space-y-2 text-muted-foreground">
                      <div className="flex justify-between">
                        <span>Status Sync:</span>
                        <span className="font-medium text-foreground capitalize">{item.sync_status || 'Pendente'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Último Sync:</span>
                        <span className="font-medium text-foreground">
                          {item.last_sync ? new Date(item.last_sync).toLocaleString() : 'Nunca'}
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 pt-2">
                      <LiveOrderConsultation integrationId={item.id} moduleName={item.instance_name} moduleId={item.module_id} />
                      <Button variant="secondary" size="sm" onClick={() => handleTest(item.id)} disabled={testingId === item.id} className="gap-2">
                        <Zap className="h-3 w-3" /> Testar
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(item.id, item.instance_name)} className="text-destructive gap-2">
                        <Trash2 className="h-3 w-3" /> Excluir
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </Tabs>
    </div>
  );
}
