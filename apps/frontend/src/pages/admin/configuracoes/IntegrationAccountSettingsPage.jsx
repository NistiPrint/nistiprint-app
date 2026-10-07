import { createElement, useCallback, useEffect, useMemo, useState } from 'react';
import { Link, Navigate, NavLink, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { ArrowLeft, Bot, CalendarClock, Cable, Loader2, Settings2, Truck } from 'lucide-react';

import IntegrationCard from '@/pages/integracoes/IntegrationCard';
import MarketplaceService from '@/services/MarketplaceService';
import LogisticaManutencao from '@/components/logistica/LogisticaManutencao';
import { JanelasLogisticas } from '@/pages/admin/configuracoes/LogisticaIntegracaoPage';
import ConfiguracoesIA from '@/pages/configuracoes/ConfiguracoesIA';
import IAPage from '@/pages/admin/IAPage';
import RessincronizarConta from '@/components/integracoes/RessincronizarConta';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const SECTIONS = [
  { id: 'geral', label: 'Geral', icon: Settings2 },
  { id: 'conexao', label: 'Conexão e vínculos', icon: Cable },
  { id: 'logistica', label: 'Logística', icon: Truck },
  { id: 'despacho', label: 'Despacho', icon: CalendarClock },
  { id: 'ia', label: 'Inteligência artificial', icon: Bot },
];

const getAccountIdentifier = (integration) => {
  const config = integration?.config || {};
  const credentials = integration?.credentials || {};
  return integration?.credential_status?.account_identifier ||
    config.account_identifiers?.primary || config.shop_id || config.seller_id || config.user_id || config.account_id ||
    credentials.account_identifiers?.primary || credentials.shop_id || credentials.seller_id || credentials.user_id || credentials.account_id || '';
};

export default function IntegrationAccountSettingsPage() {
  const { integrationId, secao } = useParams();
  const navigate = useNavigate();
  const [integrations, setIntegrations] = useState([]);
  const [moduleIcons, setModuleIcons] = useState({});
  const [linksById, setLinksById] = useState({ erp: {}, marketplace: {} });
  const [linksStatus, setLinksStatus] = useState('loading');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [testingId, setTestingId] = useState(null);
  const [syncingId, setSyncingId] = useState(null);
  const [resyncAccountIds, setResyncAccountIds] = useState([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const [installationData, modules] = await Promise.all([
        MarketplaceService.getInstalledIntegrations(),
        MarketplaceService.getAvailableModules(),
      ]);
      if (installationData.success === false) throw new Error(installationData.error || 'Falha ao carregar integrações');
      const rows = installationData.installations || [];
      setIntegrations(rows);
      try {
        const response = await fetch('/api/v2/ferramentas/ressincronizar/contas', { headers: { Accept: 'application/json' } });
        const resyncData = await response.json();
        setResyncAccountIds(resyncData.success ? (resyncData.data || []).map((row) => String(row.integration_id)) : []);
      } catch { setResyncAccountIds([]); }
      const icons = {};
      (modules || []).forEach((module) => { icons[module.id] = module.icon_url; });
      setModuleIcons(icons);
      setLoading(false);

      const erpIds = rows.filter((row) => row.module_id === 'bling').map((row) => row.id);
      const marketplaceIds = rows.filter((row) => row.module_id !== 'bling').map((row) => row.id);
      if (!erpIds.length && !marketplaceIds.length) {
        setLinksById({ erp: {}, marketplace: {} });
        setLinksStatus('loaded');
        return;
      }
      setLinksStatus('loading');
      try {
        const links = await MarketplaceService.getIntegrationLinksBatch(erpIds, marketplaceIds);
        setLinksById(links);
        setLinksStatus('loaded');
      } catch {
        setLinksStatus('error');
      }
    } catch (error) {
      setLoadError(error?.message || 'Falha ao carregar a conta conectada');
      setLoading(false);
    }
  }, []);

  const refreshLinks = useCallback(async () => {
    const erpIds = integrations.filter((row) => row.module_id === 'bling').map((row) => row.id);
    const marketplaceIds = integrations.filter((row) => row.module_id !== 'bling').map((row) => row.id);
    const links = await MarketplaceService.getIntegrationLinksBatch(erpIds, marketplaceIds);
    setLinksById(links);
    setLinksStatus('loaded');
    return true;
  }, [integrations]);

  useEffect(() => { refresh(); }, [refresh]);

  const integration = integrations.find((row) => String(row.id) === String(integrationId));
  const erpAccounts = useMemo(() => integrations.filter((row) => row.module_id === 'bling'), [integrations]);
  const sectionItems = useMemo(() => {
    if (!integration) return [];
    if (integration.module_id === 'bling') return SECTIONS.filter((item) => ['geral', 'conexao'].includes(item.id));
    const supported = integration.module_id === 'shopee' || integration.module_id === 'mercadolivre';
    const sections = supported ? SECTIONS : SECTIONS.filter((item) => ['geral', 'conexao', 'logistica', 'despacho'].includes(item.id));
    return resyncAccountIds.includes(String(integration.id))
      ? [...sections, { id: 'manutencao', label: 'Manutenção', icon: Settings2 }]
      : sections;
  }, [integration, resyncAccountIds]);

  if (secao && integration && !sectionItems.some((item) => item.id === secao)) {
    return <Navigate to={`/configuracoes/integracoes/${integrationId}`} replace />;
  }
  const activeSection = secao || 'geral';

  async function testConnection(id) {
    setTestingId(id);
    try {
      const result = await MarketplaceService.testIntegration(id);
      const details = result?.result || {};
      if (details.error || details.err_code || (details.message && details.message.includes('error'))) {
        toast.error(`Falha no teste: ${details.message || details.error || 'Erro na API'}`);
      } else {
        toast.success('Teste concluído: conexão OK');
      }
    } catch (error) {
      toast.error(error?.error || error?.message || 'Erro ao executar teste');
    } finally {
      setTestingId(null);
    }
  }

  async function renewToken(id, name) {
    if (!window.confirm(`Deseja renovar o token da integração "${name}"?`)) return;
    try {
      await MarketplaceService.renewToken(id);
      toast.success('Token renovado com sucesso');
      await refresh();
    } catch (error) {
      toast.error(`Erro ao renovar token: ${error?.message || 'Tente novamente'}`);
    }
  }

  async function syncIdentity(id, name) {
    setSyncingId(id);
    try {
      toast.info(`Sincronizando identificador da conta em "${name}"...`);
      const result = await MarketplaceService.syncAccountIdentity(id);
      if (!result.success) throw new Error(result.error || 'Falha ao sincronizar identificador da conta');
      toast.success(`Conta sincronizada: ${result.account_identifier_kind}=${result.account_identifier}`);
      await refresh();
    } catch (error) {
      toast.error(`Erro ao sincronizar conta: ${error?.message || 'Tente novamente'}`);
    } finally {
      setSyncingId(null);
    }
  }

  async function deleteIntegration(id, name) {
    if (!window.confirm(`Tem certeza que deseja remover a integração "${name}"?`)) return;
    try {
      await MarketplaceService.uninstallModule(id);
      toast.success('Integração removida com sucesso');
      navigate('/configuracoes/integracoes', { replace: true });
    } catch {
      toast.error('Erro ao remover integração');
    }
  }

  if (loading && !integrations.length) {
    return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Carregando conta" /></div>;
  }

  if (loadError) {
    return <div className="space-y-4"><Button asChild variant="ghost"><Link to="/configuracoes/integracoes"><ArrowLeft className="mr-2 h-4 w-4" />Integrações</Link></Button><p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">{loadError}</p></div>;
  }

  if (!integration) {
    return <div className="space-y-4"><Button asChild variant="ghost"><Link to="/configuracoes/integracoes"><ArrowLeft className="mr-2 h-4 w-4" />Integrações</Link></Button><p role="status" className="rounded-lg border p-4 text-sm">Conta conectada não encontrada.</p></div>;
  }

  const identifier = getAccountIdentifier(integration);
  const accountLinks = integration.module_id === 'bling'
    ? linksById.erp[String(integration.id)]
    : linksById.marketplace[String(integration.id)];

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <Button asChild variant="ghost" className="-ml-3"><Link to="/configuracoes/integracoes"><ArrowLeft className="mr-2 h-4 w-4" />Todas as integrações</Link></Button>

      <header className="flex flex-col gap-4 rounded-xl border bg-card p-4 shadow-sm sm:flex-row sm:items-center sm:p-6">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-muted">
          {moduleIcons[integration.module_id]
            ? <img src={moduleIcons[integration.module_id]} alt="" className="h-7 w-7 rounded" />
            : <Settings2 className="h-5 w-5 text-muted-foreground" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{integration.instance_name}</h1>
            <span className="rounded-md border px-2 py-0.5 text-xs uppercase tracking-wide text-muted-foreground">{integration.module_id}</span>
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${integration.is_active ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-muted text-muted-foreground'}`}>
              {integration.is_active ? 'Ativa' : 'Inativa'}
            </span>
          </div>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {identifier ? `Identificador externo: ${identifier}` : `Conta ${integration.module_id} · ID interno ${integration.id}`}
          </p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav aria-label="Configurações da conta" className="flex gap-2 overflow-x-auto rounded-xl border bg-card p-2 lg:flex-col lg:overflow-visible lg:self-start">
          {sectionItems.map(({ id, label, icon }) => (
            <NavLink
              key={id}
              to={`/configuracoes/integracoes/${integration.id}/${id}`}
              end
              className={({ isActive }) => `flex min-h-10 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isActive || (!secao && id === 'geral') ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
            >
              {createElement(icon, { className: 'h-4 w-4' })}{label}
            </NavLink>
          ))}
        </nav>

        <main className="min-w-0 space-y-5">
          {activeSection === 'geral' && <GeneralAccountSettings integration={integration} onSaved={refresh} />}
          {activeSection === 'conexao' && (
            <section className="space-y-3">
              <div><h2 className="text-lg font-semibold">Conexão e vínculos</h2><p className="text-sm text-muted-foreground">Estado da autorização, aplicativos e lojas associadas a esta conta.</p></div>
              <IntegrationCard
                integration={integration}
                type={integration.module_id === 'bling' ? 'erp' : 'marketplace'}
                moduleIcons={moduleIcons}
                erpAccounts={erpAccounts}
                key={integration.id}
                onDelete={deleteIntegration}
                onRefresh={refresh}
                onRenewToken={renewToken}
                onSyncAccountIdentity={integration.module_id === 'bling' ? undefined : syncIdentity}
                syncingAccountIdentityId={syncingId}
                onTest={testConnection}
                testingId={testingId}
                linksSummary={accountLinks ?? null}
                linksSummaryStatus={linksStatus}
                onRefreshLinks={refreshLinks}
                initiallyOpen
              />
            </section>
          )}
          {activeSection === 'logistica' && integration.module_id !== 'bling' && (
            <section className="space-y-3"><div><h2 className="text-lg font-semibold">Logística</h2><p className="text-sm text-muted-foreground">Modalidades e identificadores usados por esta conta.</p></div><LogisticaManutencao key={integration.id} integrationId={integration.id} marketplaceModuleId={integration.module_id} mode="logistica" /></section>
          )}
          {activeSection === 'despacho' && integration.module_id !== 'bling' && (
            <section className="space-y-3"><div><h2 className="text-lg font-semibold">Despacho</h2><p className="text-sm text-muted-foreground">Janelas de corte e agenda efetiva desta conta.</p></div><LogisticaManutencao key={integration.id} Janelas={JanelasLogisticas} integrationId={integration.id} marketplaceModuleId={integration.module_id} mode="despacho" /></section>
          )}
          {activeSection === 'ia' && ['shopee', 'mercadolivre'].includes(integration.module_id) && (
            <AccountAISettings key={integration.id} integration={integration} />
          )}
          {activeSection === 'manutencao' && resyncAccountIds.includes(String(integration.id)) && (
            <section className="space-y-3"><div><h2 className="text-lg font-semibold">Manutenção</h2><p className="text-sm text-muted-foreground">Ações disponíveis para esta conta conectada.</p></div><RessincronizarConta integrationId={integration.id} /></section>
          )}
        </main>
      </div>
    </div>
  );
}

function AccountAISettings({ integration }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('ia') === 'operacao' ? 'operacao' : 'configuracao';
  const changeTab = (value) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set('ia', value);
    return next;
  });

  return (
    <section className="space-y-4">
      <div><h2 className="text-lg font-semibold">Inteligência artificial</h2><p className="text-sm text-muted-foreground">Configuração de personalização aplicada somente a esta conta.</p></div>
      <Tabs value={activeTab} onValueChange={changeTab} className="space-y-4">
        <TabsList className="grid w-full max-w-xl grid-cols-2">
          <TabsTrigger value="configuracao">Configuração</TabsTrigger>
          <TabsTrigger value="operacao">Operação</TabsTrigger>
        </TabsList>
        <TabsContent value="configuracao" className="mt-0"><ConfiguracoesIA key={`config-${integration.id}`} integrationId={integration.id} embedded /></TabsContent>
        <TabsContent value="operacao" className="mt-0">
          {integration.module_id === 'shopee' ? <IAPage key={`operation-${integration.id}`} integrationId={integration.id} /> : (
            <Card><CardHeader><CardTitle>Operação de personalizados</CardTitle><CardDescription>Processe pedidos e acompanhe as extrações desta conta.</CardDescription></CardHeader><CardContent><Button asChild><Link to={`/vendas/personalizadas/mercadolivre/${integration.id}`}>Abrir personalizados desta conta</Link></Button></CardContent></Card>
          )}
        </TabsContent>
      </Tabs>
    </section>
  );
}

function GeneralAccountSettings({ integration, onSaved }) {
  const [name, setName] = useState(integration.instance_name || '');
  const [saving, setSaving] = useState(false);

  useEffect(() => { setName(integration.instance_name || ''); }, [integration.id, integration.instance_name]);

  async function saveName(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const result = await MarketplaceService.updateInstallation(integration.id, { instance_name: name });
      if (result?.installation?.instance_name !== name) throw new Error('Não foi possível confirmar o novo nome da conta.');
      toast.success('Nome da conta atualizado');
      await onSaved();
    } catch (error) {
      toast.error(error?.error || error?.message || 'Erro ao atualizar nome da conta');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Identificação da conta</CardTitle>
        <CardDescription>Use um nome fácil de reconhecer em vendas, vínculos e demais telas.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={saveName} className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="grid flex-1 gap-2">
            <Label htmlFor="integration-account-name">Nome da conta</Label>
            <Input id="integration-account-name" value={name} onChange={(event) => setName(event.target.value)} disabled={saving} />
          </div>
          <Button type="submit" disabled={saving || name === integration.instance_name}>
            {saving ? 'Salvando…' : 'Salvar nome'}
          </Button>
        </form>
        <div className="mt-6 grid gap-3 border-t pt-4 text-sm sm:grid-cols-2">
          <div><span className="text-muted-foreground">Marketplace</span><p className="mt-1 font-medium">{integration.module_id}</p></div>
          <div><span className="text-muted-foreground">ID da conta</span><p className="mt-1 font-mono text-xs">{integration.id}</p></div>
          {getAccountIdentifier(integration) && <div className="sm:col-span-2"><span className="text-muted-foreground">Identificador externo</span><p className="mt-1 font-mono text-xs">{getAccountIdentifier(integration)}</p></div>}
        </div>
      </CardContent>
    </Card>
  );
}
