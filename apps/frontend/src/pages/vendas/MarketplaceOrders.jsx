import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from '@/components/ui/select';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from '@/components/ui/table';
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger
} from '@/components/ui/tabs';
import {
    ExternalLink,
    Eye,
    Info,
    List,
    RefreshCw,
    Search
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

// Importar serviços de API
import {
    getInstalledIntegrations,
    getMarketplaceOrderDetail,
    getMarketplaceOrdersList
} from '@/services/MarketplaceService';

function MarketplaceOrders() {
  
  // Estados de Integração
  const [integrations, setIntegrations] = useState([]);
  const [selectedIntegration, setSelectedIntegration] = useState('');
  
  // Estados de Busca por ID
  const [orderId, setOrderId] = useState('');
  const [singleOrder, setSingleOrder] = useState(null);
  
  // Estados de Listagem
  const [ordersList, setOrdersList] = useState([]);
  const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0], // Last 7 days
    end: new Date().toISOString().split('T')[0]
  });
  
  // Estados Gerais
  const [loading, setLoading] = useState(false);
  const [showRawData, setShowRawData] = useState(false);
  const [activeTab, setActiveTab] = useState('search');

  // Carregar integrações instaladas
  useEffect(() => {
    loadIntegrations();
  }, []);

  const loadIntegrations = async () => {
    try {
      const response = await getInstalledIntegrations();
      if (response.success) {
        setIntegrations(response.installations || []);
        if (response.installations.length === 1) {
          setSelectedIntegration(response.installations[0].id);
        }
      } else {
        toast.error('Erro ao carregar integrações: ' + response.error);
      }
    } catch (error) {
      console.error('Erro ao carregar integrações:', error);
      toast.error('Erro ao carregar integrações');
    }
  };

  // Busca de pedido único
  const handleSearch = async () => {
    if (!selectedIntegration) return toast.error('Selecione uma integração');
    if (!orderId.trim()) return toast.error('Digite o ID do pedido');

    setLoading(true);
    setSingleOrder(null);
    setShowRawData(false);

    try {
      const response = await getMarketplaceOrderDetail(selectedIntegration, orderId.trim());
      if (response.success && response.data) {
        setSingleOrder(response.data);
      } else {
        toast.error('Pedido não encontrado: ' + (response.error || 'Verifique o ID'));
      }
    } catch (error) {
      toast.error('Erro ao buscar pedido');
    } finally {
      setLoading(false);
    }
  };

  // Listagem de pedidos
  const handleList = async () => {
    if (!selectedIntegration) return toast.error('Selecione uma integração');

    setLoading(true);
    setOrdersList([]);
    setShowRawData(false);

    try {
      const filters = {
        start_date: Math.floor(new Date(dateRange.start).getTime() / 1000),
        end_date: Math.floor(new Date(dateRange.end).getTime() / 1000) + (24 * 3600 - 1), // End of day
        page_size: 20
      };

      const response = await getMarketplaceOrdersList(selectedIntegration, filters);
      if (response.success && response.data) {
        setOrdersList(response.data);
        if (response.data.length === 0) toast.info('Nenhum pedido encontrado no período');
      } else {
        toast.error('Erro ao listar pedidos: ' + (response.error || 'Verifique os parâmetros'));
      }
    } catch (error) {
      toast.error('Erro ao listar pedidos');
    } finally {
      setLoading(false);
    }
  };

  // Formatação
  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleString('pt-BR');
    } catch {
      return dateString;
    }
  };

  const formatCurrency = (value, currency = 'BRL') => {
    if (value === undefined || value === null) return 'N/A';
    try {
      return new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format(value);
    } catch {
      return `${currency} ${value}`;
    }
  };

  const renderOrderCard = (order) => (
    <Card className="border-l-4 border-l-primary animate-in fade-in slide-in-from-bottom-4 duration-500">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="space-y-1">
          <CardTitle className="text-2xl">Pedido #{order.external_id}</CardTitle>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="outline" className="uppercase">{order.platform}</Badge>
            <span>•</span>
            <span>{formatDate(order.date_created)}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold">{formatCurrency(order.total, order.currency)}</div>
          <Badge className="mt-1" variant={
            ['paid', 'confirmed', 'ready_to_ship', 'shipped', 'delivered', 'completed'].some(s => order.status_original?.toLowerCase().includes(s))
              ? 'default' : ['cancelled', 'void'].some(s => order.status_original?.toLowerCase().includes(s))
                ? 'destructive' : 'secondary'
          }>
            {order.status_original}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
          <div className="space-y-3">
            <h3 className="font-semibold text-sm uppercase text-muted-foreground tracking-wider">Cliente</h3>
            <div className="bg-muted/40 p-3 rounded-lg space-y-2 text-sm">
              <div className="flex gap-2"><span className="text-muted-foreground w-12">Nome:</span><span className="font-medium">{order.customer?.name || 'N/A'}</span></div>
              <div className="flex gap-2"><span className="text-muted-foreground w-12">ID:</span><span className="font-mono text-xs">{order.customer?.id || 'N/A'}</span></div>
            </div>
          </div>
          <div className="space-y-3">
            <h3 className="font-semibold text-sm uppercase text-muted-foreground tracking-wider">Ações</h3>
            <div className="flex flex-col gap-2">
              <Button variant="outline" className="justify-start"><ExternalLink className="mr-2 h-4 w-4" /> Abrir na Plataforma</Button>
              <Button variant="ghost" className="justify-start text-muted-foreground" onClick={() => setShowRawData(!showRawData)}>
                <Info className="mr-2 h-4 w-4" /> {showRawData ? 'Ocultar' : 'Ver'} JSON Debug
              </Button>
            </div>
          </div>
        </div>
        {showRawData && (
          <div className="mt-6">
            <pre className="bg-slate-950 text-slate-50 p-4 rounded-md overflow-auto max-h-[400px] text-xs font-mono">
              {JSON.stringify(order.raw || order, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">Marketplace Hub</h1>
        <p className="text-muted-foreground">Consulta e listagem de pedidos em tempo real</p>
      </div>

      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-end">
            <div className="space-y-2">
              <Label>Integração Selecionada</Label>
              <Select value={selectedIntegration} onValueChange={setSelectedIntegration}>
                <SelectTrigger><SelectValue placeholder="Selecione..." /></SelectTrigger>
                <SelectContent>
                  {integrations.map(i => <SelectItem key={i.id} value={i.id}>{i.instance_name} ({i.module_id})</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            
            <div className="md:col-span-2 flex justify-end gap-2">
               <Button variant="outline" onClick={loadIntegrations} disabled={loading}><RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Atualizar Hub</Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="search" className="gap-2"><Search className="h-4 w-4" /> Buscar por ID</TabsTrigger>
          <TabsTrigger value="list" className="gap-2"><List className="h-4 w-4" /> Listar Recentes</TabsTrigger>
        </TabsList>

        <TabsContent value="search" className="space-y-6">
          <Card>
            <CardContent className="pt-6">
              <div className="flex gap-4">
                <div className="flex-1 space-y-2">
                  <Label>ID do Pedido (Externo)</Label>
                  <Input placeholder="Ex: 230101ABC123" value={orderId} onChange={e => setOrderId(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()} />
                </div>
                <Button className="self-end" onClick={handleSearch} disabled={loading || !selectedIntegration || !orderId}><Search className="h-4 w-4 mr-2" /> Buscar</Button>
              </div>
            </CardContent>
          </Card>
          {singleOrder && renderOrderCard(singleOrder)}
        </TabsContent>

        <TabsContent value="list" className="space-y-6">
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
                <div className="space-y-2">
                  <Label>Data Início</Label>
                  <Input type="date" value={dateRange.start} onChange={e => setDateRange({...dateRange, start: e.target.value})} />
                </div>
                <div className="space-y-2">
                  <Label>Data Fim</Label>
                  <Input type="date" value={dateRange.end} onChange={e => setDateRange({...dateRange, end: e.target.value})} />
                </div>
                <Button onClick={handleList} disabled={loading || !selectedIntegration}><RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Carregar Lista</Button>
              </div>
            </CardContent>
          </Card>

          {ordersList.length > 0 && (
            <Card className="animate-in fade-in duration-500">
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID Pedido</TableHead>
                      <TableHead>Data</TableHead>
                      <TableHead>Cliente</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Total</TableHead>
                      <TableHead className="w-10"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {ordersList.map((order, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium font-mono text-xs">{order.external_id}</TableCell>
                        <TableCell className="text-xs">{formatDate(order.date_created)}</TableCell>
                        <TableCell className="text-sm">{order.customer?.name || 'N/A'}</TableCell>
                        <TableCell><Badge variant="outline" className="text-[10px]">{order.status_original}</Badge></TableCell>
                        <TableCell className="text-right text-sm font-semibold">{formatCurrency(order.total, order.currency)}</TableCell>
                        <TableCell>
                          <Button size="icon" variant="ghost" onClick={() => { setSingleOrder(order); setActiveTab('search'); window.scrollTo({top: 400, behavior: 'smooth'}); }}>
                            <Eye className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default MarketplaceOrders;
