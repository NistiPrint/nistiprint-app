import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { CheckCircle2, KeyRound, Loader2, Pencil, RefreshCw, ShieldEllipsis, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import MarketplaceService from '@/services/MarketplaceService';

const initialForm = {
  module_id: 'mercadolivre',
  name: '',
  environment: 'production',
  redirect_uri: '',
  auth_base_url: '',
  token_url: '',
  is_default: true,
  is_active: true,
};

export default function IntegrationAppProfilesPage() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [providerSpecs, setProviderSpecs] = useState([]);
  const [secretValues, setSecretValues] = useState({});
  const [editingProfileId, setEditingProfileId] = useState(null);

  useEffect(() => {
    loadInitialData();
  }, []);

  useEffect(() => {
    setSecretValues({});
  }, [form.module_id]);

  const groupedProfiles = useMemo(() => {
    return profiles.reduce((acc, profile) => {
      const key = profile.module_id || 'outros';
      acc[key] = acc[key] || [];
      acc[key].push(profile);
      return acc;
    }, {});
  }, [profiles]);

  const moduleOptions = useMemo(
    () => providerSpecs.map((spec) => ({ value: spec.module_id, label: spec.display_name })),
    [providerSpecs]
  );

  const activeProviderSpec = useMemo(
    () => providerSpecs.find((spec) => spec.module_id === form.module_id) || null,
    [providerSpecs, form.module_id]
  );

  async function loadInitialData() {
    try {
      setLoading(true);
      const [profilesData, specsData] = await Promise.all([
        MarketplaceService.getAppProfiles(),
        MarketplaceService.getAppProfileSpecs(),
      ]);
      setProfiles(profilesData);
      setProviderSpecs(specsData);
      if (!initialForm.module_id && specsData[0]?.module_id) {
        setForm((prev) => ({ ...prev, module_id: specsData[0].module_id }));
      }
    } catch (error) {
      toast.error(error.error || error.message || 'Erro ao carregar configuracoes de OAuth');
    } finally {
      setLoading(false);
    }
  }

  async function loadProfiles() {
    try {
      setLoading(true);
      const data = await MarketplaceService.getAppProfiles();
      setProfiles(data);
    } catch (error) {
      toast.error(error.error || error.message || 'Erro ao carregar app profiles');
    } finally {
      setLoading(false);
    }
  }

  function updateField(field, value) {
    setForm((prev) => ({
      ...prev,
      [field]: value,
    }));
  }

  function updateSecretValue(secretKind, value) {
    setSecretValues((prev) => ({
      ...prev,
      [secretKind]: value,
    }));
  }

  function resetFormState() {
    setForm(initialForm);
    setSecretValues({});
    setEditingProfileId(null);
  }

  function startEditing(profile) {
    setEditingProfileId(profile.id);
    setForm({
      module_id: profile.module_id || initialForm.module_id,
      name: profile.name || '',
      environment: profile.environment || 'production',
      redirect_uri: profile.redirect_uri || '',
      auth_base_url: profile.auth_base_url || '',
      token_url: profile.token_url || '',
      is_default: Boolean(profile.is_default),
      is_active: profile.is_active !== false,
    });
    setSecretValues({});
  }

  async function handleSubmit(event) {
    event.preventDefault();

    if (!form.module_id || !form.name.trim() || !form.redirect_uri.trim()) {
      toast.error('Preencha modulo, nome e redirect URI.');
      return;
    }

    if (!activeProviderSpec) {
      toast.error('Modulo sem spec de credenciais.');
      return;
    }

    if (!editingProfileId) {
      const missingSecret = activeProviderSpec.app_profile_secret_fields.find(
        (field) => field.required && !String(secretValues[field.secret_kind] || '').trim()
      );
      if (missingSecret) {
        toast.error(`Preencha o campo ${missingSecret.label}.`);
        return;
      }
    }

    try {
      setSaving(true);
      const payload = {
        ...form,
        name: form.name.trim(),
        redirect_uri: form.redirect_uri.trim(),
        auth_base_url: form.auth_base_url.trim(),
        token_url: form.token_url.trim(),
        ...Object.fromEntries(
          Object.entries(secretValues).map(([key, value]) => [key, String(value || '').trim()])
        ),
      };

      if (editingProfileId) {
        await MarketplaceService.updateAppProfile(editingProfileId, payload);
      } else {
        await MarketplaceService.createAppProfile(payload);
      }

      toast.success(editingProfileId ? 'App OAuth atualizado com sucesso.' : 'App OAuth salvo com sucesso.');
      resetFormState();
      await loadProfiles();
    } catch (error) {
      toast.error(error.error || error.message || 'Erro ao salvar app profile');
    } finally {
      setSaving(false);
    }
  }

  async function handleBackfill() {
    try {
      setBackfilling(true);
      const result = await MarketplaceService.backfillIntegrationSecrets();
      toast.success(`Backfill concluido: ${result.migrated || 0} segredos migrados.`);
      await loadProfiles();
    } catch (error) {
      toast.error(error.error || error.message || 'Erro ao migrar segredos legados');
    } finally {
      setBackfilling(false);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Apps OAuth</CardTitle>
            <CardDescription>
              Um app pode autorizar varias contas instaladas. Tokens continuam isolados por instalacao.
            </CardDescription>
          </div>
          <Button variant="outline" onClick={loadProfiles} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
              Carregando perfis...
            </div>
          ) : Object.keys(groupedProfiles).length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              Nenhum app profile cadastrado ainda.
            </div>
          ) : (
            Object.entries(groupedProfiles).map(([moduleId, items]) => (
              <div key={moduleId} className="space-y-3 rounded-lg border p-4">
                <div className="flex items-center gap-2">
                  <ShieldEllipsis className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{moduleId}</h3>
                </div>
                <div className="space-y-3">
                  {items.map((profile) => (
                    <div key={profile.id} className="rounded-md border bg-muted/20 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{profile.name}</span>
                          {profile.is_default ? (
                            <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                              padrao
                            </span>
                          ) : null}
                          {!profile.is_active ? (
                            <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                              inativo
                            </span>
                          ) : null}
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => startEditing(profile)}
                          disabled={saving}
                        >
                          <Pencil className="mr-2 h-4 w-4" />
                          Editar
                        </Button>
                      </div>
                      <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                        <div>Ambiente: {profile.environment || 'production'}</div>
                        <div>Redirect URI: {profile.redirect_uri || '-'}</div>
                        <div>Auth URL: {profile.auth_base_url || '-'}</div>
                        <div>Token URL: {profile.token_url || '-'}</div>
                        {profile.module_id && (
                          <div>
                            Campos secretos: {(
                              providerSpecs.find((spec) => spec.module_id === profile.module_id)?.app_profile_secret_fields || []
                            ).map((field) => field.label).join(', ') || '-'}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}

          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold">Migracao de segredos legados</h3>
                <p className="text-sm text-muted-foreground">
                  Copia tokens antigos para o cofre criptografado sem expor valores no frontend.
                </p>
              </div>
              <Button variant="secondary" onClick={handleBackfill} disabled={backfilling}>
                {backfilling ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <KeyRound className="mr-2 h-4 w-4" />}
                Executar backfill
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{editingProfileId ? 'Editar app profile' : 'Novo app profile'}</CardTitle>
          <CardDescription>
            {editingProfileId
              ? 'Atualize os dados do app OAuth. Campos de segredo em branco mantem o valor atual criptografado.'
              : 'Cadastre as credenciais do aplicativo OAuth. Segredos sao enviados ao backend e gravados criptografados.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            {editingProfileId ? (
              <div className="flex items-center justify-between rounded-lg border bg-muted/20 p-3 text-sm">
                <span>Editando o perfil `#{editingProfileId}`.</span>
                <Button type="button" variant="ghost" size="sm" onClick={resetFormState}>
                  <X className="mr-2 h-4 w-4" />
                  Cancelar edicao
                </Button>
              </div>
            ) : null}

            <div className="space-y-2">
              <Label>Modulo</Label>
              <Select
                value={form.module_id}
                onValueChange={(value) => updateField('module_id', value)}
                disabled={Boolean(editingProfileId)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Selecione o modulo" />
                </SelectTrigger>
                <SelectContent>
                  {moduleOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Nome</Label>
              <Input value={form.name} onChange={(event) => updateField('name', event.target.value)} />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Ambiente</Label>
                <Select value={form.environment} onValueChange={(value) => updateField('environment', value)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="production">production</SelectItem>
                    <SelectItem value="sandbox">sandbox</SelectItem>
                    <SelectItem value="development">development</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="rounded-lg border p-3">
                <div className="text-sm font-medium">{activeProviderSpec?.display_name || 'Provedor'}</div>
                <p className="text-xs text-muted-foreground">
                  PKCE: {activeProviderSpec?.supports_pkce ? 'sim' : 'nao'} · Identificador: {activeProviderSpec?.account_identifier_kind || '-'}
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Redirect URI</Label>
              <Input value={form.redirect_uri} onChange={(event) => updateField('redirect_uri', event.target.value)} />
            </div>

            <div className="space-y-2">
              <Label>Authorization base URL</Label>
              <Input value={form.auth_base_url} onChange={(event) => updateField('auth_base_url', event.target.value)} />
            </div>

            <div className="space-y-2">
              <Label>Token URL</Label>
              <Input value={form.token_url} onChange={(event) => updateField('token_url', event.target.value)} />
            </div>

            {activeProviderSpec?.app_profile_secret_fields?.map((field) => (
              <div key={field.secret_kind} className="space-y-2">
                <Label>
                  {field.label}
                  {field.required ? ' *' : ''}
                </Label>
                <Input
                  type={field.input_type || 'text'}
                  placeholder={
                    editingProfileId
                      ? `${field.placeholder || field.label} (deixe em branco para manter)`
                      : (field.placeholder || '')
                  }
                  value={secretValues[field.secret_kind] || ''}
                  onChange={(event) => updateSecretValue(field.secret_kind, event.target.value)}
                />
                {field.help_text ? (
                  <p className="text-xs text-muted-foreground">{field.help_text}</p>
                ) : null}
              </div>
            ))}

            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <Label>Perfil padrao</Label>
                  <p className="text-xs text-muted-foreground">Usado em novas instalacoes.</p>
                </div>
                <Switch checked={form.is_default} onCheckedChange={(value) => updateField('is_default', value)} />
              </div>
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <Label>Ativo</Label>
                  <p className="text-xs text-muted-foreground">Permite novas autorizacoes.</p>
                </div>
                <Switch checked={form.is_active} onCheckedChange={(value) => updateField('is_active', value)} />
              </div>
            </div>

            <Button className="w-full" type="submit" disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
              {editingProfileId ? 'Atualizar app OAuth' : 'Salvar app OAuth'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
