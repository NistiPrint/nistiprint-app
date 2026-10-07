import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { ArrowLeft, Loader2, Save, TestTube2, CheckCircle2, AlertCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

const PROVIDER_OPTIONS = [
  { value: 'gemini', label: 'Gemini (Google)' },
  { value: 'openrouter', label: 'OpenRouter' },
];

// O Gemini tem catálogo fechado, então cabe um select. O OpenRouter muda de
// catálogo toda semana — uma lista fixa aqui viraria bloqueio em vez de ajuda,
// então o campo é livre, com sugestões.
const GEMINI_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash (recomendado)' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro (mais preciso)' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash (mais rápido)' },
];

const OPENROUTER_SUGGESTIONS = [
  'openrouter/auto',
  'anthropic/claude-sonnet-4',
  'openai/gpt-4o-mini',
  'google/gemini-2.0-flash-001',
];

const DEFAULT_MODEL_BY_PROVIDER = {
  gemini: 'gemini-2.5-flash',
  openrouter: 'openrouter/auto',
};

const FALLBACK_NONE = '__none__';

const DEFAULT_PROMPT = `**Role**: You are a highly specialized AI assistant for an e-commerce operation. Your primary function is to act as a data extractor and processor for customer orders, with an extreme focus on accuracy.

**Context**: We sell customized planners on Shopee. After placing an order, customers use the Shopee chat to specify the name and, occasionally, an initial they want to be printed on the planner(s) they purchased. Your task is to analyze the complete order data, the list of items purchased, and the full chat conversation to accurately extract these personalization details.

**Objective**: For a given order, identify how many customizable items there are and extract the corresponding name and/or initial for each item from the chat messages. You must extract the name with strict adherence to the customer's original spelling and determine their final decision, even if they change their mind. The final output must be a clean JSON object for our production system.`;

function ConfiguracoesIA() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedIntegrationId = searchParams.get('integration_id') || '';
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState([]);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const [promptTemplate, setPromptTemplate] = useState('');
  const [provider, setProvider] = useState('gemini');
  const [modelName, setModelName] = useState('gemini-2.5-flash');
  const [fallbackProvider, setFallbackProvider] = useState(FALLBACK_NONE);
  const [maxProcessing, setMaxProcessing] = useState(50);
  const [timeoutSeconds, setTimeoutSeconds] = useState(60);
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [scheduleTime, setScheduleTime] = useState('09:00');
  const [loadedSnapshot, setLoadedSnapshot] = useState('');

  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    let active = true;
    fetch('/api/v2/ai-personalization/accounts', { credentials: 'same-origin' })
      .then(response => response.json())
      .then(body => {
        if (!active) return;
        if (!body.success) throw new Error(body.error || 'Erro ao carregar contas');
        const available = body.accounts || [];
        setAccounts(available);
        const requested = available.find(row => String(row.integration_id) === String(selectedIntegrationId));
        const fallback = available.find(row => row.marketplace === 'shopee') || available[0];
        if (!requested && fallback) setSearchParams({ integration_id: String(fallback.integration_id) }, { replace: true });
        if (!available.length) setLoading(false);
      })
      .catch(error => { if (active) { toast.error(error.message); setLoading(false); } });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedIntegrationId || !accounts.some(row => String(row.integration_id) === String(selectedIntegrationId))) return;
    loadConfig(selectedIntegrationId);
  }, [selectedIntegrationId, accounts]);

  const snapshot = (config, marketplace) => JSON.stringify({
    prompt_template: config.prompt_template || '', provider: config.provider || 'gemini',
    model_name: config.model_name || 'gemini-2.5-flash', fallback_provider: config.fallback_provider || '',
    max_processing: Number(config.max_processing || 50), timeout_seconds: Number(config.timeout_seconds || 60),
    ...(marketplace === 'mercadolivre' ? {
      schedule_enabled: config.schedule_enabled !== false,
      schedule_hour: Number(config.schedule_hour ?? 9),
      schedule_minute: Number(config.schedule_minute ?? 0),
    } : {}),
  });

  const loadConfig = async integrationId => {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/ai-personalization/accounts/${integrationId}/config`, { credentials: 'same-origin' });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Erro ao carregar configuração');
      if (new URLSearchParams(window.location.search).get('integration_id') !== String(integrationId)) return;
      if (data.config) {
        const cfg = data.config;
        if (cfg.prompt_template) {
          // Pode vir como string ou objeto { text: ... }
          setPromptTemplate(typeof cfg.prompt_template === 'string' ? cfg.prompt_template : cfg.prompt_template.text || DEFAULT_PROMPT);
        } else {
          setPromptTemplate(DEFAULT_PROMPT);
        }
        if (cfg.provider) setProvider(cfg.provider);
        if (cfg.model_name) setModelName(String(cfg.model_name).replace(/"/g, ''));
        setFallbackProvider(cfg.fallback_provider || FALLBACK_NONE);
        if (cfg.max_processing) setMaxProcessing(cfg.max_processing);
        setTimeoutSeconds(cfg.timeout_seconds || 60);
        const hour = Number(cfg.schedule_hour ?? 9);
        const minute = Number(cfg.schedule_minute ?? 0);
        setScheduleEnabled(cfg.schedule_enabled !== false);
        setScheduleTime(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
        const marketplace = accounts.find(row => String(row.integration_id) === String(integrationId))?.marketplace;
        setLoadedSnapshot(snapshot(cfg, marketplace));
      }
    } catch {
      toast.error('Erro ao carregar configurações');
      if (new URLSearchParams(window.location.search).get('integration_id') === String(integrationId)) setPromptTemplate(DEFAULT_PROMPT);
    } finally {
      if (new URLSearchParams(window.location.search).get('integration_id') === String(integrationId)) setLoading(false);
    }
  };

  const selectedAccount = accounts.find(row => String(row.integration_id) === String(selectedIntegrationId));
  const currentSnapshot = snapshot({ prompt_template: promptTemplate, provider, model_name: modelName,
    fallback_provider: fallbackProvider === FALLBACK_NONE ? '' : fallbackProvider,
    max_processing: maxProcessing, timeout_seconds: timeoutSeconds,
    schedule_enabled: scheduleEnabled,
    schedule_hour: Number(scheduleTime.split(':')[0] || 9),
    schedule_minute: Number(scheduleTime.split(':')[1] || 0),
  }, selectedAccount?.marketplace);
  const isDirty = Boolean(loadedSnapshot && currentSnapshot !== loadedSnapshot);

  const chooseAccount = integrationId => {
    if (isDirty && !window.confirm('Há alterações não salvas. Descartar e trocar de conta?')) return;
    setTestResult(null);
    setSearchParams({ integration_id: String(integrationId) });
  };

  // Trocar de provedor troca o modelo junto: o modelo do provedor anterior
  // quase nunca existe no novo, e salvar o par inválido só falharia no servidor.
  const handleProviderChange = (novoProvider) => {
    setProvider(novoProvider);
    setModelName(DEFAULT_MODEL_BY_PROVIDER[novoProvider] || '');
    if (fallbackProvider === novoProvider) setFallbackProvider(FALLBACK_NONE);
  };

  const handleSave = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      const response = await fetch(`/api/v2/ai-personalization/accounts/${selectedIntegrationId}/config`, {
        method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
        prompt_template: promptTemplate,
        provider,
        model_name: modelName,
        fallback_provider: fallbackProvider === FALLBACK_NONE ? '' : fallbackProvider,
        max_processing: maxProcessing,
        timeout_seconds: timeoutSeconds,
        ...(selectedAccount?.marketplace === 'mercadolivre' ? {
          schedule_enabled: scheduleEnabled,
          schedule_hour: Number(scheduleTime.split(':')[0] || 9),
          schedule_minute: Number(scheduleTime.split(':')[1] || 0),
        } : {}),
      }) });
      const data = await response.json();
      if (response.ok && data.success) {
        setLoadedSnapshot(snapshot(data.config, selectedAccount?.marketplace));
        toast.success(`Configuração salva para ${selectedAccount?.name || 'esta conta'}.`);
        setTestResult({ type: 'success', message: 'Configurações aplicadas' });
      } else {
        toast.error(data.error || data.message || 'Erro ao salvar');
      }
    } catch {
      toast.error('Erro ao salvar configurações');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetch(`/api/v2/ai-personalization/accounts/${selectedIntegrationId}/preview`, {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_template: promptTemplate, provider, model_name: modelName,
          fallback_provider: fallbackProvider === FALLBACK_NONE ? '' : fallbackProvider,
          max_processing: maxProcessing, timeout_seconds: timeoutSeconds }),
      });
      const data = await response.json();
      if (response.ok && data.success) {
        setTestResult({
          type: 'success',
          message: 'Prévia concluída sem salvar personalizações.',
          detail: JSON.stringify(data.result, null, 2),
        });
        toast.success('Teste concluído!');
      } else {
        setTestResult({ type: 'error', message: data.error || data.message || 'Erro no teste' });
        toast.error('Erro no teste');
      }
    } catch (e) {
      setTestResult({ type: 'error', message: `Erro: ${e.message}` });
      toast.error('Erro ao executar teste');
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-center gap-4 mb-6">
        <Button variant="outline" onClick={() => navigate(selectedAccount?.marketplace === 'mercadolivre' ? '/vendas/personalizadas/mercadolivre' : '/vendas/personalizadas')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Personalizados
        </Button>
        <h1 className="text-2xl font-bold">Configuração de IA</h1>
      </div>
      <Card><CardContent className="space-y-2 p-5">
        <Label htmlFor="ai-account">Conta conectada</Label>
        <select id="ai-account" value={selectedIntegrationId} onChange={event => chooseAccount(event.target.value)} disabled={saving || testing} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm">
          {accounts.map(account => <option key={account.integration_id} value={account.integration_id}>{account.marketplace_label} · {account.name}</option>)}
        </select>
        {selectedAccount && <p className="text-xs text-muted-foreground">Configuração aplicada somente a {selectedAccount.marketplace_label} · {selectedAccount.name}.</p>}
      </CardContent></Card>
      {!selectedAccount && <Card><CardContent className="p-5 text-sm text-muted-foreground">Conecte uma conta Shopee ou Mercado Livre para configurar a extração.</CardContent></Card>}

      {selectedAccount?.marketplace === 'mercadolivre' && <Card>
        <CardHeader>
          <CardTitle>Extração diária</CardTitle>
          <CardDescription>Pausar o agendamento não interrompe a captura de mensagens nem a extração manual.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch id="daily-schedule-enabled" checked={scheduleEnabled} disabled={saving}
              onCheckedChange={setScheduleEnabled} />
            <Label htmlFor="daily-schedule-enabled">Executar diariamente</Label>
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="daily-schedule-time">Horário de Brasília</Label>
            <Input id="daily-schedule-time" type="time" value={scheduleTime}
              disabled={!scheduleEnabled || saving} onChange={event => setScheduleTime(event.target.value)}
              className="h-9 w-32" />
          </div>
        </CardContent>
      </Card>}

      <div className="space-y-6">
        {/* Prompt Template */}
        <Card>
          <CardHeader>
            <CardTitle>Prompt Template</CardTitle>
            <CardDescription>
              Instruções que a IA recebe para extrair nomes de personalização. Use Title Case e preserve ortografia original.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Textarea
              value={promptTemplate}
              onChange={(e) => setPromptTemplate(e.target.value)}
              className="min-h-[300px] font-mono text-sm"
              placeholder="Cole aqui o prompt template..."
            />
            <p className="text-xs text-muted-foreground mt-2">
              Dica: Use variáveis como {'{order_id}'}, {'{items}'}, {'{chat_messages}'} se o service as substitui dinamicamente.
            </p>
          </CardContent>
        </Card>

        {/* Provedor, Modelo e Limite */}
        <Card>
          <CardHeader>
            <CardTitle>Provedor e Modelo</CardTitle>
            <CardDescription>
              Escolha qual serviço executa a extração dos nomes. A troca vale imediatamente,
              sem publicar o sistema de novo.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="provider">Provedor</Label>
                <Select value={provider} onValueChange={handleProviderChange}>
                  <SelectTrigger id="provider">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROVIDER_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground mt-1">
                  Cada provedor usa sua própria chave de API, definida no servidor.
                </p>
              </div>

              <div>
                <Label htmlFor="model-name">Modelo</Label>
                {provider === 'gemini' ? (
                  <Select value={modelName} onValueChange={setModelName}>
                    <SelectTrigger id="model-name">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GEMINI_MODELS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <>
                    <Input
                      id="model-name"
                      list="openrouter-models"
                      value={modelName}
                      onChange={(e) => setModelName(e.target.value)}
                      placeholder="openrouter/auto"
                    />
                    <datalist id="openrouter-models">
                      {OPENROUTER_SUGGESTIONS.map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                    <p className="text-xs text-muted-foreground mt-1">
                      <code>openrouter/auto</code> deixa o OpenRouter escolher o modelo a cada
                      pedido. Qualquer <code>fornecedor/modelo</code> também é aceito.
                    </p>
                  </>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="fallback-provider">Provedor reserva</Label>
                <Select value={fallbackProvider} onValueChange={setFallbackProvider}>
                  <SelectTrigger id="fallback-provider">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={FALLBACK_NONE}>Nenhum</SelectItem>
                    {PROVIDER_OPTIONS.filter((o) => o.value !== provider).map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground mt-1">
                  Usado só se o provedor principal falhar, com o modelo padrão dele.
                </p>
              </div>
              <div>
                <Label htmlFor="max-processing">Limite de Pedidos</Label>
                <Input
                  id="max-processing"
                  type="number"
                  min={1}
                  max={500}
                  value={maxProcessing}
                  onChange={(e) => setMaxProcessing(parseInt(e.target.value) || 50)}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Quantos pedidos processar por execução.
                </p>
              </div>
              <div>
                <Label htmlFor="timeout-seconds">Timeout (segundos)</Label>
                <Input id="timeout-seconds" type="number" min={1} max={600} value={timeoutSeconds}
                  onChange={e => setTimeoutSeconds(Number(e.target.value) || 60)} />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Resultado do Teste */}
        {testResult && (
          <Card className={testResult.type === 'success' ? 'border-green-300 bg-green-50' : 'border-red-300 bg-red-50'}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {testResult.type === 'success' ? (
                  <CheckCircle2 className="h-5 w-5 text-green-600" />
                ) : (
                  <AlertCircle className="h-5 w-5 text-red-600" />
                )}
                {testResult.type === 'success' ? 'Sucesso' : 'Erro'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm">{testResult.message}</p>
              {testResult.detail && (
                <pre className="mt-2 bg-white/50 p-3 rounded text-xs overflow-x-auto">
                  <code>{testResult.detail}</code>
                </pre>
              )}
            </CardContent>
          </Card>
        )}

        {/* Ações */}
        <div className="flex gap-3 justify-end">
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={testing || !selectedAccount}
          >
            {testing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <TestTube2 className="mr-2 h-4 w-4" />
            )}
            Testar Prompt
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || !selectedAccount || !isDirty}
          >
            {saving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Salvar Configurações
          </Button>
        </div>
      </div>
    </div>
  );
}

export default ConfiguracoesIA;
