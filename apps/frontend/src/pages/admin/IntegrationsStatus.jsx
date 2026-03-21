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

  const openDetails = (integration) => {
    setSelectedIntegration(integration);
    setIsDetailsOpen(true);
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiado para a área de transferência!");
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">Instâncias Instaladas</h2>
        <Button onClick={onAddClick} className="flex items-center gap-2">
          <Plus className="h-4 w-4" />
          Nova Integração
        </Button>
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
                    <Button variant="secondary" size="sm" onClick={() => handleRenew(item.id)} className="gap-2">
                      <RefreshCw className="h-3 w-3" /> Renovar
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => handleTest(item.id)} disabled={testingId === item.id} className="gap-2">
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
    </div>
  );
}