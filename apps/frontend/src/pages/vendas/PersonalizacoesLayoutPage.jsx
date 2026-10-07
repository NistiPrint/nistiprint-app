import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useLocation, useNavigate, Outlet } from 'react-router-dom';

const SHOPEE_PATH = '/vendas/personalizadas';
const MERCADOLIVRE_PATH = '/vendas/personalizadas/mercadolivre';

export default function PersonalizacoesLayoutPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const isMercadoLivre = location.pathname.includes('/mercadolivre');
  const activeSource = isMercadoLivre ? 'mercadolivre' : 'shopee';

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold">Personalizados</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Consulte pedidos e personalize nomes por canal de venda.
        </p>
      </header>

      <Tabs
        value={activeSource}
        onValueChange={(source) => navigate(source === 'shopee' ? SHOPEE_PATH : MERCADOLIVRE_PATH)}
        className="space-y-4"
      >
        <TabsList aria-label="Canal de venda" className="grid h-auto w-full max-w-md grid-cols-2">
          <TabsTrigger value="shopee" className="py-2.5">Shopee</TabsTrigger>
          <TabsTrigger value="mercadolivre" className="py-2.5">Mercado Livre</TabsTrigger>
        </TabsList>
        <TabsContent value={activeSource} className="mt-0 focus-visible:outline-none">
          <Outlet />
        </TabsContent>
      </Tabs>
    </div>
  );
}
