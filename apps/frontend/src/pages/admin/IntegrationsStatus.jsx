import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import MarketplaceService from '@/services/MarketplaceService';
import * as integracaoCanalService from '@/services/integracaoCanalService';
import IntegrationCard from '@/pages/integracoes/IntegrationCard';
import { Database, RefreshCw, ShoppingCart, Sparkles } from 'lucide-react';

export default function IntegrationsStatus({ onAddClick }) {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState(null);
  const [syncingAction, setSyncingAction] = useState(null);
  const [moduleIcons, setModuleIcons] = useState({});

  useEffect(() => {
    fetchIntegrations();
    fetchModules();
  }, []);

  const erps = useMemo(
    () => integrations.filter((item) => item.module_id === 'bling'),
    [integrations]
  );
  const marketplaces = useMemo(
    () => integrations.filter((item) => item.module_id !== 'bling'),
    [integrations]
  );

  async function fetchModules() {
    try {
      const modules = await MarketplaceService.getAvailableModules();
      const icons = {};
      modules.forEach((module) => {
        icons[module.id] = module.icon_url;
      });
      setModuleIcons(icons);
    } catch (error) {
      console.error('Erro ao carregar icones:', error);
    }
  }

  async function fetchIntegrations() {
    try {
      setLoading(true);
      const data = await MarketplaceService.getInstalledIntegrations();
      setIntegrations(data.success === false ? [] : data.installations || []);
    } catch (error) {
      console.error(error);
      toast.error('Erro ao carregar integracoes');
    } finally {
      setLoading(false);
    }
  }

  async function handleTest(id) {
    try {
      setTestingId(id);
      toast.info('Executando teste de conexao...');
      const data = await MarketplaceService.testIntegration(id);
      const result = data?.result || {};
      const isError = result.error || result.err_code || (result.message && result.message.includes('error'));
      if (isError) {
        toast.error(`Falha no teste: ${result.message || result.error || 'Erro na API'}`);
      } else {
        toast.success('Teste concluido: conexao OK');
      }
    } catch (error) {
      toast.error(error.response?.data?.error || error.message || 'Erro ao executar teste');
    } finally {
      setTestingId(null);
    }
  }

  async function handleRenewToken(instanceId, instanceName) {
    if (!confirm(`Deseja renovar o token da integracao "${instanceName}"?`)) return;
    try {
      toast.info('Renovando token...');
      await integracaoCanalService.renewToken(instanceId);
      toast.success('Token renovado com sucesso');
      await fetchIntegrations();
    } catch (error) {
      toast.error(`Erro ao renovar token: ${error.message || 'Tente novamente'}`);
    }
  }

  async function handleDelete(id, name) {
    if (!confirm(`Tem certeza que deseja remover a integracao "${name}"?`)) return;
    try {
      await MarketplaceService.uninstallModule(id);
      toast.success('Integracao removida com sucesso');
      await fetchIntegrations();
    } catch (error) {
      toast.error('Erro ao remover integracao');
    }
  }

  async function handleImportFromFirebase() {
    setSyncingAction('import');
    try {
      const result = await integracaoCanalService.importTokensFromFirebase();
      if (result.status === 'success') {
        toast.success('Tokens importados do Firebase para o cofre');
        await fetchIntegrations();
      } else if (result.status === 'partial_success') {
        toast.warning('Importacao parcial do Firebase concluida');
        await fetchIntegrations();
      } else {
        toast.error('Falha ao importar tokens do Firebase');
      }
    } catch (error) {
      toast.error('Falha ao importar tokens do Firebase');
    } finally {
      setSyncingAction(null);
    }
  }

  async function handlePublishToFirebase() {
    setSyncingAction('publish');
    try {
      const result = await integracaoCanalService.publishTokensToFirebase();
      if (result.status === 'success') {
        toast.success('Tokens publicados no Firebase');
      } else if (result.status === 'partial_success') {
        toast.warning('Publicacao parcial no Firebase concluida');
      } else {
        toast.error('Falha ao publicar tokens no Firebase');
      }
    } catch (error) {
      toast.error('Falha ao publicar tokens no Firebase');
    } finally {
      setSyncingAction(null);
    }
  }

  function renderEmptyState(type) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/20 p-5 text-center">
        <p className="text-sm text-muted-foreground">
          {type === 'erp'
            ? 'Nenhuma conta ERP conectada.'
            : 'Nenhum canal de venda conectado.'}
        </p>
      </div>
    );
  }

  function renderSection(title, icon, items, type) {
    return (
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {icon}
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
          </div>
          <span className="text-xs text-muted-foreground">{items.length}</span>
        </div>

        {items.length === 0 ? (
          renderEmptyState(type)
        ) : (
          <div className="space-y-2">
            {items.map((integration) => (
              <IntegrationCard
                key={integration.id}
                integration={integration}
                type={type}
                moduleIcons={moduleIcons}
                erpAccounts={erps}
                onDelete={handleDelete}
                onRefresh={fetchIntegrations}
                onRenewToken={handleRenewToken}
                onTest={handleTest}
                testingId={testingId}
              />
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Integracoes</h2>
          <p className="text-sm text-muted-foreground">Contas, vinculos e rotas de NF.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={handleImportFromFirebase} disabled={syncingAction !== null}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingAction === 'import' ? 'animate-spin' : ''}`} />
            Baixar tokens do Firebase
          </Button>
          <Button variant="outline" onClick={handlePublishToFirebase} disabled={syncingAction !== null}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingAction === 'publish' ? 'animate-spin' : ''}`} />
            Publicar no Firebase
          </Button>
          <Button onClick={onAddClick}>
            <Sparkles className="mr-2 h-4 w-4" />
            Nova integracao
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="rounded-xl border p-8 text-center text-sm text-muted-foreground">
          Carregando integracoes...
        </div>
      ) : (
        <>
          {renderSection('Contas ERP', <Database className="h-4 w-4 text-muted-foreground" />, erps, 'erp')}
          {renderSection('Canais de Venda', <ShoppingCart className="h-4 w-4 text-muted-foreground" />, marketplaces, 'marketplace')}
        </>
      )}
    </div>
  );
}
