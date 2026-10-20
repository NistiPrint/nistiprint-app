import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '@/services/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const STATUS = { not_checked: 'Acesso ainda não verificado', pending: 'Agendado', available: 'Disponível', forbidden: 'Acesso negado pela plataforma', failed: 'Aguardando nova tentativa' };
const date = value => value ? new Date(value).toLocaleString('pt-BR') : '—';
const ERRORS = {
  analytics_budget_wait: 'Aguardando disponibilidade no orçamento de chamadas da conta.',
  credentials_missing: 'Revise a conexão e as credenciais desta conta.',
  account_platform_mismatch: 'Verifique se a conta está ativa e oferece este recurso.',
  advertiser_not_unique_or_unavailable: 'Verifique a conta de anúncios e o acesso do aplicativo na plataforma.',
  provider_access_forbidden: 'O aplicativo não tem acesso a este recurso. Confira as permissões na plataforma.',
};

export default function AccountInsightsSettings({ integration }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal) => {
    try {
      const response = await api.get(`/marketplace/installed/${integration.id}/insights`, { signal });
      if (!response.data.success) throw new Error(response.data.error);
      setData(response.data.data); setError('');
    } catch (e) { if (!signal?.aborted) setError(e.response?.data?.error || e.message || 'Falha ao consultar dados.'); }
  }, [integration.id]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); load(controller.signal);
    const timer = setInterval(() => load(controller.signal), 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [load]);
  const act = async (capability, action) => {
    setBusy(true);
    try { await api.post(`/marketplace/installed/${integration.id}/insights`, { capability, action }); await load(); }
    catch (e) { setError(e.response?.data?.error || 'Não foi possível salvar a configuração.'); }
    finally { setBusy(false); }
  };
  return <div className="space-y-4">
    <Card><CardHeader><CardTitle>Dados e inteligência</CardTitle></CardHeader><CardContent className="space-y-3">
      <p>Os detalhes recebidos pelos webhooks alimentam os indicadores automaticamente. Repasses, visitas e publicidade usam coletas complementares desta conta.</p>
      {error && <p role="alert" className="text-destructive">{error} <Button variant="outline" onClick={() => load()}>Tentar novamente</Button></p>}
      {!data && !error && <p role="status">Carregando cobertura…</p>}
      {data && <><dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div><dt>Pedidos no histórico</dt><dd>{data.coverage.orders || 0}</dd></div>
        <div><dt>Período disponível</dt><dd>{data.coverage.from || '—'} a {data.coverage.to || '—'}</dd></div>
        <div><dt>Última atualização</dt><dd>{date(data.coverage.last_synced_at)}</dd></div>
        <div><dt>Pendências de projeção / complementos</dt><dd>{data.coverage.pending || 0} / {data.coverage.enrichment_pending || 0}</dd></div>
        <div><dt>Pendência mais antiga</dt><dd>{date(data.coverage.oldest_pending_at)}</dd></div>
        <div><dt>Pedidos sem comprador / destino identificado</dt><dd>{data.coverage.missing_buyer || 0} / {data.coverage.missing_geography || 0}</dd></div>
      </dl><Button asChild variant="outline"><Link to={data.gestao_url}>Abrir Gestão nesta conta</Link></Button></>}
    </CardContent></Card>
    {data?.capabilities.map(cap => <Card key={cap.capability}><CardHeader><CardTitle className="text-base">{cap.label}</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
      <p>{cap.enabled ? STATUS[cap.status] || cap.status : 'Pausado / desabilitado'}</p>
      {cap.status === 'forbidden' && <p className="text-amber-700">Verifique o acesso do aplicativo na plataforma antes de retomar. As permissões da conexão não são alteradas automaticamente.</p>}
      {cap.error_code && <p>{ERRORS[cap.error_code] || 'A consulta não foi concluída. Verifique a conexão e a disponibilidade do recurso na plataforma.'}</p>}
      <p>Última tentativa: {date(cap.checked_at)} · Próxima tentativa: {cap.status === 'forbidden' ? 'Suspensa até retomada manual' : cap.enabled ? date(cap.next_attempt_at) : '—'}</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy} variant="outline" onClick={() => act(cap.capability, cap.enabled ? 'pause' : 'enable')}>{cap.enabled ? 'Pausar' : 'Habilitar'}</Button>
        {cap.enabled && <><Button disabled={busy} variant="outline" onClick={() => act(cap.capability, 'resume')}>Retomar / tentar agora</Button><Button disabled={busy} variant="outline" onClick={() => act(cap.capability, 'backfill')}>Recuperar histórico</Button></>}
      </div>
    </CardContent></Card>)}
  </div>;
}
