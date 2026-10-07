import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, Outlet } from 'react-router-dom';

const BASE_PATH = '/vendas/personalizadas';

async function fetchAccounts(path) {
  const response = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  const body = await response.json();
  if (!response.ok || body.success === false) throw new Error(body.message || 'Falha ao carregar contas.');
  return body.data ? { ...body.data, success: body.success } : body;
}

export default function PersonalizacoesLayoutPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchAccounts('/api/v2/ai-personalization/accounts'),
      fetchAccounts('/api/v2/mercadolivre/integracoes/personalizacoes'),
    ]).then(([personalization, mercadolivre]) => {
      if (cancelled) return;
      const merged = new Map();
      [...(personalization.accounts || []), ...(mercadolivre.accounts || []).map(account => ({
        ...account, marketplace: 'mercadolivre', marketplace_label: 'Mercado Livre',
      }))].forEach(account => merged.set(`${account.marketplace}:${account.integration_id}`, account));
      setAccounts([...merged.values()].filter(account => account.is_active !== false));
    }).catch(error => { if (!cancelled) setLoadError(error.message); });
    return () => { cancelled = true; };
  }, []);

  const accountPath = (account) => account.marketplace === 'mercadolivre'
    ? `${BASE_PATH}/mercadolivre/${account.integration_id}`
    : `${BASE_PATH}/shopee/${account.integration_id}`;

  const activeAccount = accounts.find(account => location.pathname === accountPath(account));
  const activeValue = activeAccount ? `${activeAccount.marketplace}:${activeAccount.integration_id}` : '';

  useEffect(() => {
    if (!accounts.length) return;
    const path = location.pathname;
    if (path === BASE_PATH || path === `${BASE_PATH}/`) {
      const firstShopee = accounts.find(account => account.marketplace === 'shopee');
      if (firstShopee) navigate(accountPath(firstShopee), { replace: true });
      else navigate(`${BASE_PATH}/mercadolivre`, { replace: true });
      return;
    }
    if (path === `${BASE_PATH}/mercadolivre`) {
      const firstMeli = accounts.find(account => account.marketplace === 'mercadolivre');
      if (firstMeli) navigate(accountPath(firstMeli), { replace: true });
    }
  }, [accounts, location.pathname, navigate]);

  const visibleTabs = useMemo(() => accounts.map(account => ({
    ...account,
    value: `${account.marketplace}:${account.integration_id}`,
    path: accountPath(account),
    label: `${account.marketplace_label} · ${account.name}`,
  })), [accounts]);

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold">Personalizados</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Consulte pedidos e personalize nomes por canal de venda.
        </p>
      </header>

      {loadError && <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">{loadError}</p>}
      {!loadError && accounts.length === 0 && <p className="rounded border p-4 text-sm">Nenhuma conta de marketplace conectada.</p>}
      {!!visibleTabs.length && (
        <Tabs value={activeValue} onValueChange={value => {
          const tab = visibleTabs.find(item => item.value === value);
          if (tab) navigate(tab.path);
        }} className="space-y-4">
          <TabsList aria-label="Conta de venda" className="h-auto w-full flex-wrap justify-start gap-1">
            {visibleTabs.map(tab => <TabsTrigger key={tab.value} value={tab.value} className="py-2.5">{tab.label}</TabsTrigger>)}
          </TabsList>
          {activeAccount && <TabsContent value={activeValue} className="mt-0 focus-visible:outline-none"><Outlet context={{ integrationId: activeAccount.integration_id, marketplace: activeAccount.marketplace, account: activeAccount, singleShopeeAccount: accounts.filter(account => account.marketplace === 'shopee').length === 1 }} /></TabsContent>}
        </Tabs>
      )}
    </div>
  );
}
