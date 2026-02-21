import LiveOrderConsultation from '@/components/marketplace/LiveOrderConsultation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import MarketplaceService from '@/services/MarketplaceService';
import { AlertCircle, CheckCircle2, Copy, ExternalLink, Plus, RefreshCw, Settings2, Trash2, Zap } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

export default function IntegrationsStatus({ onAddClick }) {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [testingId, setTestingId] = useState(null);
  const [selectedIntegration, setSelectedIntegration] = useState(null);
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      const data = await MarketplaceService.getInstalledIntegrations();
      if (data.success === false) {
        // Em caso de erro, define como array vazio
        setIntegrations([]);
      } else {
        // Caso contrário, extrai o array installations do objeto retornado
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

  const handleRenew = async (id) => {
    try {
      toast.info("Iniciando renovação manual...");
      const data = await MarketplaceService.renewToken(id);
      
      if (data.status === 'success') {
        toast.success(data.message);
        fetchIntegrations();
      } else {
        toast.error(data.message || "Erro na renovação");
      }
    } catch (error) {
      const errorMsg = error.response?.data?.message || error.response?.data?.error || "Erro na comunicação com o servidor";
      toast.error(errorMsg);
    }
  };

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

  const handleSyncFirestore = async () => {
    try {
      setSyncing(true);
      toast.info("Sincronizando com Firestore...");
      const response = await fetch('/api/v2/integracoes/sync-firestore', { method: 'POST' });
      const data = await response.json();
      if (data.status === 'success') {
        toast.success(data.message);
        fetchIntegrations();
      } else {
        toast.error(data.message);
      }
    } catch (error) {
      toast.error("Erro na sincronização");
    } finally {
      setSyncing(false);
    }
  };

  const openDetails = (integration) => {
    setSelectedIntegration(integration);
    setIsDetailsOpen(true);
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiado para a área de transferência!");
  };

  const getWebhookUrl = (integration) => {
    const baseUrl = window.location.origin;
    return `${baseUrl}/api/v2/webhooks/${integration.module_id}/${integration.id}`;
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">Integrações Instaladas</h2>
        <div className="flex gap-2">
          <Button 
            variant="outline" 
            size="sm"
            onClick={handleSyncFirestore} 
            disabled={syncing}
            className="flex items-center gap-2"
          >
            <RefreshCw className={`h-3 w-3 ${syncing ? 'animate-spin' : ''}`} />
            Sync Legacy
          </Button>
          <Button onClick={onAddClick} className="flex items-center gap-2">
            <Plus className="h-4 w-4" />
            Nova Integração
          </Button>
        </div>
      </div>

      <div className="grid gap-6">
        {loading ? (
          <div className="flex justify-center p-12">
            <RefreshCw className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : integrations.length === 0 ? (
          <Card>
            <CardContent className="p-12 text-center flex flex-col items-center gap-4">
              <p className="text-muted-foreground">Nenhuma integração encontrada.</p>
              <Button onClick={onAddClick} variant="outline">
                Adicionar Integração
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {integrations.map((item) => (
              <Card key={item.id} className="overflow-hidden">
                <CardHeader className="bg-muted/50 pb-4">
                  <div className="flex justify-between items-start">
                    <div>
                      <Badge variant="secondary" className="mb-2">
                        {item.module_id ? item.module_id.toUpperCase() : 'UNKNOWN'}
                      </Badge>
                      <CardTitle className="text-xl">{item.instance_name}</CardTitle>
                    </div>
                    <div className="flex gap-2">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        className="h-8 w-8"
                        onClick={() => openDetails(item)}
                      >
                        <Settings2 className="h-4 w-4" />
                      </Button>
                      {item.is_active ? (
                        <CheckCircle2 className="h-5 w-5 text-green-500" />
                      ) : (
                        <AlertCircle className="h-5 w-5 text-red-500" />
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-6 space-y-4">
                  <div className="text-sm space-y-2">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Status Sync:</span>
                      <span className="font-medium capitalize">
                        {item.sync_status || 'Pendente'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Último Sync:</span>
                      <span className="font-medium">
                        {item.last_sync ? new Date(item.last_sync).toLocaleString() : 'Nunca'}
                      </span>
                    </div>
                    {item.expires_at && (
                        <div className="flex justify-between">
                        <span className="text-muted-foreground">Expira em:</span>
                        <span className="font-medium">
                            {new Date(item.expires_at).toLocaleString()}
                        </span>
                        </div>
                    )}
                  </div>

                  {item.refresh_error && (
                    <div className="bg-red-50 border border-red-100 p-2 rounded text-xs text-red-700 mt-2">
                      <p className="font-bold mb-1 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" /> Erro:
                      </p>
                      {item.refresh_error}
                    </div>
                  )}

                                      <div className="flex gap-2">

                                        <LiveOrderConsultation 

                                          integrationId={item.id} 

                                          moduleName={item.instance_name} 

                                          moduleId={item.module_id}

                                        />

                                        <Button 

                                          variant="secondary"

                                          className="flex-1 flex items-center gap-2" 

                                          onClick={() => handleRenew(item.id)}

                                        >

                                          <RefreshCw className="h-4 w-4" />

                                          Renovar

                                        </Button>

                  
                    <Button 
                      variant="outline"
                      className="flex items-center gap-2" 
                      onClick={() => handleTest(item.id)}
                      disabled={testingId === item.id}
                    >
                      <Zap className={`h-4 w-4 ${testingId === item.id ? 'animate-pulse text-yellow-500' : ''}`} />
                      Testar
                    </Button>
                    <Button 
                      variant="destructive"
                      size="icon"
                      onClick={() => handleDelete(item.id, item.instance_name)}
                      title="Excluir Integração"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Details Modal */}
      <Dialog open={isDetailsOpen} onOpenChange={setIsDetailsOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="h-5 w-5" />
              Configurações Técnicas: {selectedIntegration?.instance_name}
            </DialogTitle>
            <DialogDescription>
              Informações para configuração de webhooks e monitoramento.
            </DialogDescription>
          </DialogHeader>

          {selectedIntegration && (
            <div className="space-y-6 py-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-muted-foreground text-xs uppercase">ID da Instância</Label>
                  <div className="flex items-center gap-2 bg-muted p-2 rounded-md">
                    <code className="text-xs font-mono flex-1">{selectedIntegration.id}</code>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => copyToClipboard(selectedIntegration.id)}>
                      <Copy className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-muted-foreground text-xs uppercase">Módulo</Label>
                  <div className="p-2 bg-muted rounded-md text-sm font-medium">
                    {selectedIntegration.module_id.toUpperCase()}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label className="text-sm font-bold flex items-center gap-2 text-primary">
                  URL de Webhook (Callback)
                </Label>
                <div className="flex items-center gap-2">
                  <Input 
                    readOnly 
                    value={getWebhookUrl(selectedIntegration)}
                    className="font-mono text-xs bg-muted/50"
                  />
                  <Button variant="outline" size="icon" onClick={() => copyToClipboard(getWebhookUrl(selectedIntegration))}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-[0.7rem] text-muted-foreground italic">
                  Cadastre esta URL no painel da {selectedIntegration.module_id.toUpperCase()} para receber notificações de pedidos e estoque em tempo real.
                </p>
              </div>

              <div className="border-t pt-4">
                <Label className="text-xs font-bold uppercase text-muted-foreground mb-3 block">Dados de Configuração</Label>
                <div className="bg-muted/30 rounded-lg p-3 overflow-hidden">
                  <pre className="text-[10px] font-mono whitespace-pre-wrap break-all max-h-[150px] overflow-y-auto">
                    {JSON.stringify(selectedIntegration.config || {}, null, 2)}
                  </pre>
                </div>
              </div>

              <div className="flex justify-end gap-2 border-t pt-4">
                <Button variant="outline" onClick={() => setIsDetailsOpen(false)}>Fechar</Button>
                <Button variant="ghost" className="gap-2" onClick={() => window.open(getWebhookUrl(selectedIntegration), '_blank')}>
                  <ExternalLink className="h-4 w-4" />
                  Testar Endpoint
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}