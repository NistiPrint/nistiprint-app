import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, Settings2 } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import ConfiguracoesIA from '@/pages/configuracoes/ConfiguracoesIA';
import IAPage from '@/pages/admin/IAPage';

const VALID_TABS = new Set(['configuracao', 'operacao']);

export default function InteligenciaArtificialPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = VALID_TABS.has(searchParams.get('aba')) ? searchParams.get('aba') : 'configuracao';
  const selectedIntegrationId = searchParams.get('integration_id');

  useEffect(() => {
    if (!VALID_TABS.has(searchParams.get('aba'))) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set('aba', 'configuracao');
        return next;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const changeTab = (value) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set('aba', value);
    return next;
  });

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Inteligência artificial</h1>
        <p className="mt-1 text-muted-foreground">Configure modelos por conta e acompanhe a operação.</p>
      </header>
      <Tabs value={activeTab} onValueChange={changeTab} className="space-y-5">
        <TabsList className="grid w-full max-w-xl grid-cols-2">
          <TabsTrigger value="configuracao"><Settings2 className="mr-2 h-4 w-4" />Configuração</TabsTrigger>
          <TabsTrigger value="operacao"><Bot className="mr-2 h-4 w-4" />Operação</TabsTrigger>
        </TabsList>
        <TabsContent value="configuracao" className="mt-0"><ConfiguracoesIA /></TabsContent>
        <TabsContent value="operacao" className="mt-0"><IAPage integrationId={selectedIntegrationId || null} /></TabsContent>
      </Tabs>
    </div>
  );
}
