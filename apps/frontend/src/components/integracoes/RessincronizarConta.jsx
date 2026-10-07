import { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function RessincronizarConta({ integrationId = null }) {
  const fixedAccount = integrationId !== null && integrationId !== undefined;
  const [accounts, setAccounts] = useState([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [loading, setLoading] = useState(fixedAccount);
  const [days, setDays] = useState('7');
  const [limit, setLimit] = useState('');
  const [runningId, setRunningId] = useState(null);
  const [result, setResult] = useState(null);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/ferramentas/ressincronizar/contas', { headers: { Accept: 'application/json' } });
      const body = await response.json();
      if (!body.success) throw new Error(body.message || 'Erro ao carregar contas.');
      setAccounts(body.data || []);
      setAccountsLoaded(true);
    } catch (error) {
      toast.error(error.message || 'Não foi possível carregar as contas.');
      if (fixedAccount) setResult({ unavailable: error.message || 'Não foi possível carregar a conta.' });
    } finally {
      setLoading(false);
    }
  }, [fixedAccount]);

  useEffect(() => {
    if (fixedAccount) loadAccounts();
  }, [fixedAccount, integrationId, loadAccounts]);

  const account = fixedAccount ? accounts.find((row) => String(row.integration_id) === String(integrationId)) : null;

  const run = async (target) => {
    if (!target) return;
    setRunningId(target.integration_id);
    setResult(null);
    try {
      const response = await fetch('/api/v2/ferramentas/ressincronizar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ integration_id: target.integration_id, dias: parseInt(days, 10) || 7, limite: limit ? parseInt(limit, 10) : null }),
      });
      const body = await response.json();
      if (!body.success) throw new Error(body.message || 'Erro na ressincronização.');
      setResult({ account: target.nome, ...body.data });
      toast.success(`${target.nome}: ${body.message}`);
    } catch (error) {
      toast.error(`Erro: ${error.message}`);
    } finally {
      setRunningId(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ressincronizar a partir da origem</CardTitle>
        <CardDescription>{fixedAccount ? 'Relê pedidos pendentes desta conta diretamente no marketplace e os processa pela integração.' : 'Relê pedidos pendentes direto no marketplace e reprocessa pela pipeline normal de ingest. Use quando a base estiver defasada ou incoerente.'}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? <Loader2 className="h-5 w-5 animate-spin" aria-label="Carregando conta" /> : fixedAccount && !account ? (
          <p role="status" className="text-sm text-muted-foreground">{result?.unavailable || 'Esta conta não está habilitada para ressincronização.'}</p>
        ) : (
          <>
            {!fixedAccount && <div className="space-y-2">
              {!accountsLoaded ? <Button onClick={loadAccounts} variant="outline"><RefreshCw className="mr-2 h-4 w-4" />Carregar contas de marketplace</Button> : accounts.length === 0 ? <p className="text-sm text-muted-foreground">Nenhuma conta de marketplace ativa encontrada.</p> : null}
            </div>}
            <div className="flex flex-wrap gap-4">
              <div className="w-32 space-y-2"><Label htmlFor="ressync-days">Últimos dias</Label><Input id="ressync-days" type="number" min="1" value={days} onChange={(event) => setDays(event.target.value)} /></div>
              <div className="w-40 space-y-2"><Label htmlFor="ressync-limit">Limite (opcional)</Label><Input id="ressync-limit" type="number" min="1" placeholder="sem limite" value={limit} onChange={(event) => setLimit(event.target.value)} /></div>
            </div>
            {fixedAccount ? <div className="rounded-md border p-3"><p className="font-medium text-sm">{account.nome}</p><p className="mt-0.5 text-xs text-muted-foreground">{account.module_id}{account.shop_id ? ` · shop_id ${account.shop_id}` : ''}</p><Button className="mt-3" size="sm" variant="outline" disabled={runningId !== null} onClick={() => run(account)}>{runningId === account.integration_id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}Ressincronizar</Button></div> : accountsLoaded && <div className="space-y-2">{accounts.map((target) => <div key={target.integration_id} className="flex items-center justify-between gap-3 rounded-md border p-3"><div className="min-w-0"><div className="flex items-center gap-2"><span className="font-medium text-sm">{target.nome}</span><span className={`rounded-full px-2 py-0.5 text-[10px] ${target.rota === 'direta' ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'}`}>{target.rota === 'direta' ? 'API própria' : 'via Bling'}</span></div><p className="mt-0.5 text-xs text-muted-foreground">{target.module_id}{target.shop_id ? ` · shop_id ${target.shop_id}` : ''}</p></div><Button size="sm" variant="outline" disabled={runningId !== null} onClick={() => run(target)}>{runningId === target.integration_id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}Ressincronizar</Button></div>)}</div>}
          </>
        )}
        {result && !result.unavailable && <div className="space-y-1 rounded-md border p-3 text-sm"><p className="font-medium">{result.account}</p><p className="text-muted-foreground">{result.listados} listados na origem · {result.processados} reprocessados · {result.total_erros || 0} erros</p>{result.erros?.length > 0 && <ul className="mt-2 space-y-0.5 text-xs text-destructive">{result.erros.map((error) => <li key={error.externo}>{error.externo}: {error.erro}</li>)}</ul>}</div>}
      </CardContent>
    </Card>
  );
}
