import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import MarketplaceService from '@/services/MarketplaceService';
import * as integracaoCanalService from '@/services/integracaoCanalService';
import IntegrationCard from '@/pages/integracoes/IntegrationCard';
import { Database, RefreshCw, ShoppingCart, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function IntegrationsStatus({ onAddClick }) {
  const navigate = useNavigate();
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState(null);
  const [syncingAction, setSyncingAction] = useState(null);
  const [syncingAccountIdentityId, setSyncingAccountIdentityId] = useState(null);
  const [moduleIcons, setModuleIcons] = useState({});
  const [erpLinksById, setErpLinksById] = useState({});
  const [marketplaceLinksById, setMarketplaceLinksById] = useState({});
  const [linkSummaryStatus, setLinkSummaryStatus] = useState('loading');
  const integrationsRef = useRef(integrations);
  integrationsRef.current = integrations;

  const erps = useMemo(
    () => integrations.filter((item) => item.module_id === 'bling'),
    [integrations]
  );
  const marketplaces = useMemo(
    () => integrations.filter((item) => item.module_id !== 'bling'),
    [integrations]
  );

  const fetchLinkSummaries = useCallback(async (installations) => {
    setLinkSummaryStatus('loading');
    const erpIds = installations
      .filter((item) => item.module_id === 'bling')
      .map((item) => item.id);
    const marketplaceIds = installations
      .filter((item) => item.module_id !== 'bling')
      .map((item) => item.id);

    if (erpIds.length === 0 && marketplaceIds.length === 0) {
      setErpLinksById({});
      setMarketplaceLinksById({});
      setLinkSummaryStatus('loaded');
      return true;
    }

    try {
      const result = await MarketplaceService.getIntegrationLinksBatch(erpIds, marketplaceIds);
      setErpLinksById(result.erp || {});
      setMarketplaceLinksById(result.marketplace || {});
      setLinkSummaryStatus('loaded');
      return true;
    } catch (error) {
      console.error('Erro ao carregar vínculos das integrações:', error);
      setLinkSummaryStatus('error');
      return false;
    }
  }, []);

  const refreshLinkSummaries = useCallback(
    () => fetchLinkSummaries(integrationsRef.current),
    [fetchLinkSummaries]
  );

  const fetchModules = useCallback(async () => {
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
  }, []);

  const fetchIntegrations = useCallback(async () => {
    try {
      setLoading(true);
      const data = await MarketplaceService.getInstalledIntegrations();
      const installations = data.success === false ? [] : data.installations || [];
      integrationsRef.current = installations;
      setIntegrations(installations);
      setLoading(false);
      await fetchLinkSummaries(installations);
    } catch (error) {
      console.error(error);
      toast.error('Erro ao carregar integracoes');
    } finally {
      setLoading(false);
    }
  }, [fetchLinkSummaries]);

  useEffect(() => {
    fetchIntegrations();
    fetchModules();
  }, [fetchIntegrations, fetchModules]);

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

  async function handleSyncAccountIdentity(instanceId, instanceName) {
    try {
      setSyncingAccountIdentityId(instanceId);
      toast.info(`Sincronizando identificador da conta em "${instanceName}"...`);
      const result = await MarketplaceService.syncAccountIdentity(instanceId);
      if (!result.success) {
        throw new Error(result.error || 'Falha ao sincronizar identificador da conta');
      }
      toast.success(
        `Conta sincronizada: ${result.account_identifier_kind}=${result.account_identifier}`
      );
      await fetchIntegrations();
    } catch (error) {
      toast.error(`Erro ao sincronizar conta: ${error.message || 'Tente novamente'}`);
    } finally {
      setSyncingAccountIdentityId(null);
    }
  }

  async function handleDelete(id, name) {
    if (!confirm(`Tem certeza que deseja remover a integracao "${name}"?`)) return;
    try {
      await MarketplaceService.uninstallModule(id);
      toast.success('Integracao removida com sucesso');
      await fetchIntegrations();
    } catch {
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
    } catch {
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
    } catch {
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
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted/70">{icon}</span>
            <h3 className="text-sm font-semibold tracking-wide">{title}</h3>
          </div>
          <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium tabular-nums text-muted-foreground">
            {items.length}
          </span>
        </div>

        {items.length === 0 ? (
          renderEmptyState(type)
        ) : (
          <div className="space-y-3">
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
                onSyncAccountIdentity={handleSyncAccountIdentity}
                syncingAccountIdentityId={syncingAccountIdentityId}
                onTest={handleTest}
                testingId={testingId}
                linksSummary={
                  (type === 'erp' ? erpLinksById : marketplaceLinksById)[String(integration.id)] ?? null
                }
                linksSummaryStatus={linkSummaryStatus}
                onRefreshLinks={refreshLinkSummaries}
                onConfigure={() => navigate(`/configuracoes/integracoes/${integration.id}`)}
              />
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <div className="space-y-7">
      <div className="flex flex-col gap-4 rounded-xl border bg-card p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Integrações conectadas</h2>
          <p className="mt-1 text-sm text-muted-foreground">Contas, vínculos e emissão de notas fiscais.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleImportFromFirebase} disabled={syncingAction !== null}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingAction === 'import' ? 'animate-spin' : ''}`} />
            Baixar tokens do Firebase
          </Button>
          <Button variant="outline" size="sm" onClick={handlePublishToFirebase} disabled={syncingAction !== null}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingAction === 'publish' ? 'animate-spin' : ''}`} />
            Publicar no Firebase
          </Button>
          <Button size="sm" onClick={onAddClick}>
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
