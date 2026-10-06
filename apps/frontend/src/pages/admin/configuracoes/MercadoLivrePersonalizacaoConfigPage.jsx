import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

const initial = {
  enabled: false, capture_enabled: false, extraction_enabled: false,
  provider: 'gemini', model_name: 'gemini-2.5-flash', fallback_provider: '',
  timeout_seconds: 60, max_processing: 50, schedule_hour: 9, schedule_minute: 0,
  prompt_template: '',
};

export default function MercadoLivrePersonalizacaoConfigPage() {
  const { integration_id: integrationId } = useParams();
  const [config, setConfig] = useState(initial);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!integrationId) {
      fetch('/api/v2/mercadolivre/integracoes/personalizacoes', { credentials: 'same-origin' })
        .then(async response => {
          const body = await response.json();
          if (!response.ok || body.success === false) throw new Error(body.message || 'Falha ao carregar contas');
          setAccounts(body.data.accounts || []);
        })
        .catch(error => toast.error(error.message))
        .finally(() => setLoading(false));
      return;
    }
    fetch(`/api/v2/mercadolivre/integracoes/${integrationId}/personalizados/config`, { credentials: 'same-origin' })
      .then(async response => {
        const body = await response.json();
        if (!response.ok || body.success === false) throw new Error(body.message || 'Falha ao carregar configuração');
        setConfig(current => ({ ...current, ...body.data.config, fallback_provider: body.data.config.fallback_provider || '' }));
      })
      .catch(error => toast.error(error.message))
      .finally(() => setLoading(false));
  }, [integrationId]);
  const change = (key, value) => setConfig(current => ({ ...current, [key]: value }));
  const save = async event => {
    event.preventDefault(); setSaving(true);
    try {
      const response = await fetch(`/api/v2/mercadolivre/integracoes/${integrationId}/personalizados/config`, {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...config, fallback_provider: config.fallback_provider || null }),
      });
      const body = await response.json();
      if (!response.ok || body.success === false) throw new Error(body.message || 'Falha ao salvar configuração');
      setConfig(current => ({ ...current, ...body.data.config, fallback_provider: body.data.config.fallback_provider || '' }));
      toast.success('Configuração Mercado Livre salva para esta conta.');
    } catch (error) { toast.error(error.message); }
    finally { setSaving(false); }
  };
  if (loading) return <main className="p-6">Carregando configuração…</main>;
  if (!integrationId) return (
    <main className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-2xl font-semibold">Configuração · Mercado Livre</h1><p className="text-sm text-muted-foreground">Cada conta possui credenciais de IA, captura e agenda próprias.</p></div>
      {!accounts.length && <p className="rounded border p-4 text-sm">Nenhuma conta Mercado Livre conectada.</p>}
      <div className="grid gap-3 md:grid-cols-2">{accounts.map(account => <Link key={account.integration_id} to={`/configuracoes/personalizacao/mercadolivre/${account.integration_id}`} className="rounded-lg border bg-card p-4 hover:border-primary"><h2 className="font-medium">{account.name}</h2><p className="text-sm text-muted-foreground">Conta {account.account_user_id || account.integration_id}</p><p className="mt-2 text-xs">Configurar esta conta →</p></Link>)}</div>
    </main>
  );
  const checkbox = (key, title, description) => (
    <label className="flex gap-3 rounded border p-3">
      <input type="checkbox" checked={Boolean(config[key])} onChange={event => change(key, event.target.checked)} className="mt-1" />
      <span><span className="block text-sm font-medium">{title}</span><span className="text-xs text-muted-foreground">{description}</span></span>
    </label>
  );
  return (
    <main className="mx-auto max-w-3xl space-y-5 p-6">
      <div>
        <Link className="text-sm text-muted-foreground" to={`/vendas/personalizadas/mercadolivre/${integrationId}`}>← Voltar aos pedidos</Link>
        <h1 className="mt-2 text-2xl font-semibold">Configuração de personalização · Mercado Livre</h1>
        <p className="text-sm text-muted-foreground">Conta conectada {integrationId}. Estes parâmetros não alteram as configurações da Shopee nem de outras contas.</p>
      </div>
      <form onSubmit={save} className="space-y-5 rounded-lg border bg-card p-5">
        <div className="space-y-2">
          {checkbox('enabled', 'Habilitar personalização', 'Chave principal desta conta Mercado Livre.')}
          {checkbox('capture_enabled', 'Capturar e reconciliar mensagens privadas', 'Ativa a sincronização contínua das conversas pós-venda.')}
          {checkbox('extraction_enabled', 'Habilitar extração por IA', 'Permite extração manual e diária dos pedidos elegíveis.')}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">Provedor<select value={config.provider} onChange={event => change('provider', event.target.value)} className="mt-1 w-full rounded border bg-background p-2"><option value="gemini">Gemini</option><option value="openrouter">OpenRouter</option></select></label>
          <label className="text-sm">Modelo<input value={config.model_name} onChange={event => change('model_name', event.target.value)} className="mt-1 w-full rounded border bg-background p-2" required /></label>
          <label className="text-sm">Fallback<select value={config.fallback_provider} onChange={event => change('fallback_provider', event.target.value)} className="mt-1 w-full rounded border bg-background p-2"><option value="">Sem fallback</option><option value="gemini">Gemini</option><option value="openrouter">OpenRouter</option></select></label>
          <label className="text-sm">Limite de pacotes por execução<input type="number" min="1" max="500" value={config.max_processing} onChange={event => change('max_processing', Number(event.target.value))} className="mt-1 w-full rounded border bg-background p-2" /></label>
          <label className="text-sm">Timeout (segundos)<input type="number" min="1" max="600" value={config.timeout_seconds} onChange={event => change('timeout_seconds', Number(event.target.value))} className="mt-1 w-full rounded border bg-background p-2" /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">Hora diária<input type="number" min="0" max="23" value={config.schedule_hour} onChange={event => change('schedule_hour', Number(event.target.value))} className="mt-1 w-full rounded border bg-background p-2" /></label>
            <label className="text-sm">Minuto<input type="number" min="0" max="59" value={config.schedule_minute} onChange={event => change('schedule_minute', Number(event.target.value))} className="mt-1 w-full rounded border bg-background p-2" /></label>
          </div>
        </div>
        <label className="block text-sm">Prompt específico desta conta<textarea value={config.prompt_template || ''} onChange={event => change('prompt_template', event.target.value)} rows={8} maxLength={30000} placeholder="Prompt padrão Mercado Livre será usado se ficar vazio." className="mt-1 w-full rounded border bg-background p-2 font-mono text-xs" /></label>
        <p className="text-xs text-muted-foreground">A execução diária usa America/Sao_Paulo. A credencial de IA pode ter cota própria por conta no ambiente Mercado Livre; nenhuma chave da Shopee é reutilizada.</p>
        <button disabled={saving} className="rounded bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">{saving ? 'Salvando…' : 'Salvar configuração'}</button>
      </form>
    </main>
  );
}
