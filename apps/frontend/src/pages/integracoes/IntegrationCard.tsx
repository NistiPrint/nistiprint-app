import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import MarketplaceService from '@/services/MarketplaceService';
import { ChevronDown, Database, MoreHorizontal, Plus, RefreshCw, Trash2, Zap } from 'lucide-react';

import LinkForm from './LinkForm';
import LinkTable from './LinkTable';
import NfEmitterBanner from './NfEmitterBanner';

export interface IntegrationInstance {
  id: number;
  module_id: string;
  instance_name: string;
  is_active: boolean;
  app_profile_id?: string | number | null;
  config?: Record<string, any>;
  credential_status?: {
    token_status?: string;
    connection_status?: string;
    last_sync?: string;
    actions?: { can_refresh?: boolean };
  };
}

export interface ErpLink {
  id: string;
  erp_integration_id: number;
  marketplace_integration_id: number | null;
  marketplace_module_id?: string;
  erp_store_id: string;
  store_name?: string;
  process_webhooks?: boolean;
  ingest_origin_mode?: string;
  nf_emission_mode?: string;
  marketplace?: IntegrationInstance & { catalog_only?: boolean };
  erp?: IntegrationInstance;
}

interface IntegrationCardProps {
  integration: IntegrationInstance;
  type: 'erp' | 'marketplace';
  moduleIcons: Record<string, string>;
  erpAccounts?: IntegrationInstance[];
  onDelete: (id: number, name: string) => void;
  onRefresh: () => void;
  onRenewToken?: (id: number, name: string) => void;
  onTest?: (id: number) => void;
  testingId?: number | null;
}

interface AppProfile {
  id: string | number;
  name: string;
  environment?: string;
  is_default?: boolean;
  is_active?: boolean;
}

const TOKEN_LABELS: Record<string, string> = {
  valid: 'Token OK',
  expiring_soon: 'Expira logo',
  expired: 'Expirado',
  missing: 'Sem token',
  refresh_failed: 'Falha token',
  refresh_warning: 'Atencao',
  reauth_required: 'Reautorizar',
  not_required: 'Sem token',
};

const alertTokens = ['expired', 'missing', 'refresh_failed', 'reauth_required'];

function tokenLabel(status?: IntegrationInstance['credential_status']) {
  const tokenStatus = status?.token_status || 'unknown';
  return TOKEN_LABELS[tokenStatus] || 'Token ?';
}

function isTokenAlert(status?: IntegrationInstance['credential_status']) {
  return alertTokens.includes(status?.token_status || '');
}

function linkSummary(link: ErpLink, isErp: boolean) {
  const name = isErp
    ? link.marketplace?.instance_name || link.marketplace_module_id || 'Origem'
    : link.erp?.instance_name || `Bling ${link.erp_integration_id}`;
  return `${name} / ${link.erp_store_id}`;
}

export default function IntegrationCard({
  integration,
  type,
  moduleIcons,
  erpAccounts = [],
  onDelete,
  onRefresh,
  onRenewToken,
  onTest,
  testingId,
}: IntegrationCardProps) {
  const isErp = type === 'erp';
  const [open, setOpen] = useState(false);
  const [links, setLinks] = useState<ErpLink[]>([]);
  const [blingAccounts, setBlingAccounts] = useState<IntegrationInstance[]>(erpAccounts);
  const [loadingLinks, setLoadingLinks] = useState(false);
  const [showLinkForm, setShowLinkForm] = useState(false);
  const [editingLink, setEditingLink] = useState<ErpLink | null>(null);
  const [defaultNfeLinkId, setDefaultNfeLinkId] = useState('none');
  const [savingNfe, setSavingNfe] = useState(false);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [customFieldId, setCustomFieldId] = useState('');
  const [companyId, setCompanyId] = useState('');
  const [savingParams, setSavingParams] = useState(false);
  const [appProfiles, setAppProfiles] = useState<AppProfile[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [selectedAppProfileId, setSelectedAppProfileId] = useState(
    integration.app_profile_id ? String(integration.app_profile_id) : 'none'
  );
  const [savingAppProfile, setSavingAppProfile] = useState(false);

  const nfeLinks = useMemo(
    () => links.filter((link) => (link.nf_emission_mode || 'bling') === 'bling'),
    [links]
  );
  const defaultNfeLink = useMemo(
    () => nfeLinks.find((link) => String(link.id) === defaultNfeLinkId) || null,
    [nfeLinks, defaultNfeLinkId]
  );
  const firstLink = links[0];
  const extraLinks = Math.max(links.length - 1, 0);
  const alertToken = isTokenAlert(integration.credential_status);

  const loadLinks = useCallback(async () => {
    try {
      setLoadingLinks(true);
      const linksUrl = isErp
        ? `/api/v2/erp-links/erp/${integration.id}/links`
        : `/api/v2/erp-links/marketplace/${integration.id}/links`;
      const res = await fetch(linksUrl);
      if (!res.ok) return;
      const data = await res.json();
      const loadedLinks: ErpLink[] = data.data || [];
      setLinks(loadedLinks);

      if (!isErp) {
        const savedDefault = integration.config?.default_nfe_link_id;
        if (savedDefault) {
          setDefaultNfeLinkId(String(savedDefault));
        } else {
          const onlyNfe = loadedLinks.filter((link) => (link.nf_emission_mode || 'bling') === 'bling');
          setDefaultNfeLinkId(onlyNfe.length === 1 ? String(onlyNfe[0].id) : 'none');
        }
      }
    } catch (err) {
      console.error('Erro ao carregar vinculos:', err);
    } finally {
      setLoadingLinks(false);
    }
  }, [integration.id, isErp, integration.config?.default_nfe_link_id]);

  const loadBlingAccounts = useCallback(async () => {
    if (isErp) return;
    if (erpAccounts.length > 0) {
      setBlingAccounts(erpAccounts);
      return;
    }
    try {
      const res = await fetch('/api/v2/integracoes/bling/accounts');
      if (res.ok) {
        const data = await res.json();
        setBlingAccounts(data.accounts || data.data || []);
      }
    } catch (err) {
      console.error('Erro ao carregar contas Bling:', err);
    }
  }, [isErp, erpAccounts]);

  useEffect(() => {
    loadLinks();
    loadBlingAccounts();
  }, [loadLinks, loadBlingAccounts]);

  useEffect(() => {
    if (isErp) {
      setCustomFieldId(String(integration.config?.id_campo_personalizado || ''));
      setCompanyId(String(integration.config?.company_id || ''));
    }
  }, [isErp, integration.config]);

  useEffect(() => {
    setSelectedAppProfileId(integration.app_profile_id ? String(integration.app_profile_id) : 'none');
  }, [integration.app_profile_id]);

  const loadAppProfiles = useCallback(async () => {
    try {
      setLoadingProfiles(true);
      const data = await MarketplaceService.getInstallationAppProfiles(integration.id);
      setAppProfiles(data.profiles || []);
      setSelectedAppProfileId(data.app_profile_id ? String(data.app_profile_id) : 'none');
    } catch (error) {
      console.error('Erro ao carregar app profiles:', error);
    } finally {
      setLoadingProfiles(false);
    }
  }, [integration.id]);

  useEffect(() => {
    if (open) {
      loadAppProfiles();
    }
  }, [open, loadAppProfiles]);

  async function handleSaveParams() {
    try {
      setSavingParams(true);
      const res = await fetch(`/api/v2/marketplace/installed/${integration.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: {
            ...(integration.config || {}),
            id_campo_personalizado: customFieldId ? parseInt(customFieldId) : null,
            company_id: companyId?.trim() || null,
          },
        }),
      });
      if (!res.ok) throw new Error();
      toast.success('Parametros salvos');
      onRefresh();
    } catch {
      toast.error('Erro ao salvar parametros');
    } finally {
      setSavingParams(false);
    }
  }

  async function handleSaveDefaultNfe(linkId: string) {
    const selected = links.find((link) => String(link.id) === linkId);
    try {
      setSavingNfe(true);
      const res = await fetch(`/api/v2/marketplace/installed/${integration.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: {
            ...(integration.config || {}),
            default_nfe_link_id: selected ? String(selected.id) : null,
            default_nfe_erp_integration_id: selected?.erp_integration_id || null,
            default_nfe_shop_id: selected?.erp_store_id || null,
          },
        }),
      });
      if (!res.ok) throw new Error();
      setDefaultNfeLinkId(linkId);
      toast.success('Emissor de NF salvo');
      onRefresh();
    } catch {
      toast.error('Erro ao salvar emissor de NF');
    } finally {
      setSavingNfe(false);
    }
  }

  async function handleSaveAppProfile() {
    try {
      setSavingAppProfile(true);
      await MarketplaceService.updateInstallationAppProfile(
        integration.id,
        selectedAppProfileId === 'none' ? null : selectedAppProfileId
      );
      toast.success('App OAuth atualizado');
      await loadAppProfiles();
      onRefresh();
    } catch (error: any) {
      toast.error(error?.error || error?.message || 'Erro ao atualizar app OAuth');
    } finally {
      setSavingAppProfile(false);
    }
  }

  async function handleSaveLink(data: {
    erp_integration_id: number;
    erp_store_id: string;
    store_name: string;
    ingest_origin_mode: string;
    nf_emission_mode: string;
  }) {
    const payload = {
      erp_integration_id: data.erp_integration_id,
      marketplace_module_id: integration.module_id,
      shop_id: data.erp_store_id,
      erp_store_id: data.erp_store_id,
      store_name: data.store_name || undefined,
      process_webhooks: true,
      ingest_origin_mode: data.ingest_origin_mode,
      nf_emission_mode: data.nf_emission_mode,
    };

    try {
      const url = editingLink
        ? `/api/v2/erp-links/links/${editingLink.id}/config`
        : `/api/v2/erp-links/marketplace/${integration.id}/links`;
      const res = await fetch(url, {
        method: editingLink ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const error = await res.json();
        throw new Error(error.message || 'Erro ao salvar vinculo');
      }

      const result = await res.json();
      const savedLink = result.data;
      if ((savedLink?.nf_emission_mode || data.nf_emission_mode) === 'bling' && defaultNfeLinkId === 'none') {
        await handleSaveDefaultNfe(String(savedLink.id));
      }

      toast.success('Vinculo salvo');
      setShowLinkForm(false);
      setEditingLink(null);
      loadLinks();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Erro ao salvar vinculo');
    }
  }

  async function handleDeleteLink(link: ErpLink) {
    if (!confirm('Tem certeza que deseja remover este vinculo?')) return;
    try {
      const res = await fetch(`/api/v2/erp-links/links/${link.id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error();
      if (String(link.id) === defaultNfeLinkId) {
        await handleSaveDefaultNfe('none');
      }
      toast.success('Vinculo removido');
      loadLinks();
    } catch {
      toast.error('Erro ao remover vinculo');
    }
  }

  function startNewLink() {
    setEditingLink(null);
    setShowLinkForm(true);
    setOpen(true);
  }

  function handleStartEdit(link: ErpLink) {
    setEditingLink(link);
    setShowLinkForm(true);
    setOpen(true);
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border bg-background">
        <div className="flex items-center gap-3 p-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
            {moduleIcons[integration.module_id] ? (
              <img src={moduleIcons[integration.module_id]} alt={integration.module_id} className="h-5 w-5 rounded" />
            ) : (
              <Database className="h-4 w-4 text-muted-foreground" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate font-medium">{integration.instance_name}</span>
              <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase">
                {integration.module_id}
              </Badge>
              <span className={`h-2 w-2 rounded-full ${integration.is_active ? 'bg-emerald-500' : 'bg-muted-foreground'}`} />
            </div>
            <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className={alertToken ? 'text-destructive' : ''}>{tokenLabel(integration.credential_status)}</span>
              <span>•</span>
              <span>{links.length} vinculo{links.length === 1 ? '' : 's'}</span>
              {firstLink && (
                <>
                  <span>•</span>
                  <span className="truncate">{linkSummary(firstLink, isErp)}{extraLinks ? ` +${extraLinks}` : ''}</span>
                </>
              )}
              {!isErp && defaultNfeLink && (
                <>
                  <span>•</span>
                  <span className="truncate">NF {defaultNfeLink.erp?.instance_name || `Bling ${defaultNfeLink.erp_integration_id}`}</span>
                </>
              )}
            </div>
          </div>

          <div className="hidden items-center gap-1 sm:flex">
            {!isErp && onTest && (
              <Button variant="ghost" size="sm" onClick={() => onTest(integration.id)} disabled={testingId === integration.id}>
                <Zap className="h-4 w-4" />
              </Button>
            )}
            {!isErp && onRenewToken && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onRenewToken(integration.id, integration.instance_name)}
                disabled={!integration.credential_status?.actions?.can_refresh}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            )}
            {!isErp && (
              <Button variant="ghost" size="sm" onClick={startNewLink}>
                <Plus className="h-4 w-4" />
              </Button>
            )}
          </div>

          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 px-2">
              <MoreHorizontal className="h-4 w-4 sm:hidden" />
              <ChevronDown className={`hidden h-4 w-4 transition-transform sm:block ${open ? 'rotate-180' : ''}`} />
            </Button>
          </CollapsibleTrigger>
        </div>

        <CollapsibleContent>
          <div className="space-y-3 border-t p-3">
            {!isErp && (
              <NfEmitterBanner
                defaultNfeLinkId={defaultNfeLinkId}
                nfeLinks={nfeLinks}
                saving={savingNfe}
                onSave={handleSaveDefaultNfe}
              />
            )}

            {isErp && (
              <Collapsible open={paramsOpen} onOpenChange={setParamsOpen}>
                <CollapsibleTrigger asChild>
                  <Button variant="outline" size="sm" className="w-full justify-between">
                    Parametros Bling
                    <ChevronDown className={`h-4 w-4 transition-transform ${paramsOpen ? 'rotate-180' : ''}`} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label className="text-xs">Campo customizado</Label>
                      <Input value={customFieldId} onChange={(event) => setCustomFieldId(event.target.value)} placeholder="2797770" />
                    </div>
                    <div className="grid gap-1.5">
                      <Label className="text-xs">Company ID</Label>
                      <Input value={companyId} onChange={(event) => setCompanyId(event.target.value)} placeholder="Company ID" />
                    </div>
                  </div>
                  <Button className="mt-3" size="sm" onClick={handleSaveParams} disabled={savingParams}>
                    {savingParams ? 'Salvando...' : 'Salvar'}
                  </Button>
                </CollapsibleContent>
              </Collapsible>
            )}

            <div className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <span className="text-sm font-medium">App OAuth vinculado</span>
                  <p className="text-xs text-muted-foreground">
                    Escolhe qual aplicacao do provedor esta associada a esta instalacao.
                  </p>
                </div>
                <Badge variant="outline" className="text-[10px] uppercase">
                  {integration.module_id}
                </Badge>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
                <Select value={selectedAppProfileId} onValueChange={setSelectedAppProfileId}>
                  <SelectTrigger disabled={loadingProfiles || savingAppProfile}>
                    <SelectValue placeholder={loadingProfiles ? 'Carregando perfis...' : 'Selecione um app OAuth'} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Sem app profile</SelectItem>
                    {appProfiles.map((profile) => (
                      <SelectItem key={profile.id} value={String(profile.id)}>
                        {profile.name}
                        {profile.environment ? ` (${profile.environment})` : ''}
                        {profile.is_default ? ' - padrao' : ''}
                        {!profile.is_active ? ' - inativo' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  onClick={handleSaveAppProfile}
                  disabled={loadingProfiles || savingAppProfile}
                >
                  {savingAppProfile ? 'Salvando...' : 'Salvar app'}
                </Button>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{isErp ? 'Vinculos' : 'ERPs vinculados'}</span>
              {!isErp && !showLinkForm && (
                <Button size="sm" variant="outline" onClick={startNewLink}>
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Vinculo
                </Button>
              )}
            </div>

            {showLinkForm && !isErp && (
              <LinkForm
                editingLink={editingLink}
                blingAccounts={blingAccounts}
                onSave={handleSaveLink}
                onCancel={() => {
                  setShowLinkForm(false);
                  setEditingLink(null);
                }}
              />
            )}

            {loadingLinks ? (
              <div className="rounded-md border border-dashed py-5 text-center text-sm text-muted-foreground">
                Carregando vinculos...
              </div>
            ) : (
              <LinkTable
                links={links}
                viewMode={isErp ? 'erp' : 'marketplace'}
                defaultNfeLinkId={defaultNfeLinkId}
                onEdit={!isErp ? handleStartEdit : undefined}
                onDelete={!isErp ? handleDeleteLink : undefined}
              />
            )}

            <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
              {!isErp && onTest && (
                <Button variant="outline" size="sm" onClick={() => onTest(integration.id)} disabled={testingId === integration.id}>
                  Testar
                </Button>
              )}
              {!isErp && onRenewToken && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onRenewToken(integration.id, integration.instance_name)}
                  disabled={!integration.credential_status?.actions?.can_refresh}
                >
                  Renovar token
                </Button>
              )}
              <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onDelete(integration.id, integration.instance_name)}>
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                Excluir
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}
