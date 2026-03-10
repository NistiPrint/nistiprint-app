import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, Eye, Package, Calendar, Filter, Download, MoreHorizontal } from 'lucide-react';
import { toast } from 'sonner';

// Importar serviço de API para pedidos unificados
import { getUnifiedOrders, getOrderStatusOptions, updateOrderStatus, getCanalVendaOptions } from '@/services/orderService';

function UnifiedOrdersPage() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('');
  const [selectedOrigin, setSelectedOrigin] = useState('');
  const [selectedChannel, setSelectedChannel] = useState(''); // Novo estado para filtro de canal
  const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0], // Last 30 days
    end: new Date().toISOString().split('T')[0]
  });
  
  const [statusOptions, setStatusOptions] = useState([]);
  const [canalVendaOptions, setCanalVendaOptions] = useState([]); // Novo estado para opções de canal
  const [totalOrders, setTotalOrders] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage, setPerPage] = useState(50);

  // Carregar pedidos e opções de status
  useEffect(() => {
    loadOrders();
    loadStatusOptions();
    loadCanalVendaOptions(); // Carregar opções de canal
  }, [currentPage, selectedStatus, selectedOrigin, selectedChannel, dateRange.start, dateRange.end, searchTerm, perPage]); // Adicionar dependências para recarregar quando filtros mudam

  const loadOrders = async () => {
    setLoading(true);
    try {
      // Parâmetros de filtro
      const filters = {
        searchTerm,
        status: selectedStatus,
        origin: selectedOrigin,
        canal_venda_id: selectedChannel, // Incluir filtro de canal
        startDate: dateRange.start,
        endDate: dateRange.end,
        page: currentPage,
        perPage: perPage
      };

      const response = await getUnifiedOrders(filters);
      if (response.success) {
        setOrders(response.data?.orders || []);
        setTotalOrders(response.data?.total || 0);
      } else {
        toast.error('Erro ao carregar pedidos: ' + (response.error || 'Verifique os parâmetros'));
      }
    } catch (error) {
      toast.error('Erro ao carregar pedidos');
    } finally {
      setLoading(false);
    }
  };

  const handleFilterApply = () => {
    setCurrentPage(1); // Resetar página ao aplicar novos filtros
    loadOrders();
  };

  const loadStatusOptions = async () => {
    try {
      const response = await getOrderStatusOptions();
      if (response.success) {
        setStatusOptions(response.data?.status_options || response.data || []);
      } else {
        toast.error('Erro ao carregar opções de status');
      }
    } catch (error) {
      toast.error('Erro ao carregar opções de status');
    }
  };

  const loadCanalVendaOptions = async () => {
    try {
      const response = await getCanalVendaOptions();
      if (response.success) {
        setCanalVendaOptions(response.data?.canal_venda_options || response.data || []);
      } else {
        toast.error('Erro ao carregar opções de canal de venda');
      }
    } catch (error) {
      toast.error('Erro ao carregar opções de canal de venda');
    }
  };

  const handleStatusChange = async (orderId, newStatus) => {
    try {
      // O backend ainda não tem a rota de atualização de status, então simulamos
      toast.warning('Funcionalidade de alteração de status ainda não implementada no backend.');
      // return; 
      // const response = await updateOrderStatus(orderId, newStatus);
      // if (response.success) {
      //   // Atualizar o pedido na lista local
      //   setOrders(prevOrders => 
      //     prevOrders.map(order => 
      //       order.id === orderId ? { ...order, situacao_pedido: response.data.situacao_pedido } : order
      //     )
      //   );
      //   toast.success('Status do pedido atualizado com sucesso');
      // } else {
      //   toast.error('Erro ao atualizar status: ' + (response.error || 'Verifique os parâmetros'));
      // }
    } catch (error) {
      toast.error('Erro ao atualizar status do pedido');
    }
  };

  // Nao precisamos filtrar localmente, a API já faz isso
  // const filteredOrders = orders.filter(order => {
  //   const matchesSearch = !searchTerm || 
  //     order.numero_pedido?.toLowerCase().includes(searchTerm.toLowerCase()) ||
  //     order.codigo_pedido_externo?.toLowerCase().includes(searchTerm.toLowerCase()) ||
  //     order.cliente_nome?.toLowerCase().includes(searchTerm.toLowerCase());
    
  //   const matchesStatus = !selectedStatus || order.situacao_pedido?.nome === selectedStatus; // Usar situacao_pedido.nome
  //   const matchesOrigin = !selectedOrigin || order.origem?.toLowerCase().includes(selectedOrigin.toLowerCase());
  //   // Filtro por canal já está na API, não precisa filtrar localmente novamente
    
  //   return matchesSearch && matchesStatus && matchesOrigin;
  // });

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleDateString('pt-BR');
    } catch {
      return dateString;
    }
  };

  const formatCurrency = (value) => {
    if (value === undefined || value === null) return 'N/A';
    try {
      return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
    } catch {
      return `R$ ${value}`;
    }
  };

  const getStatusColor = (statusName) => {
    if (!statusName) return 'secondary';
    
    const statusLower = statusName.toLowerCase();
    if (['pago', 'processando', 'pago_bling'].includes(statusLower)) return 'default';
    if (['cancelado'].includes(statusLower)) return 'destructive';
    if (['entregue'].includes(statusLower)) return 'success';
    if (['pendente'].includes(statusLower)) return 'secondary';
    if (['enviado'].includes(statusLower)) return 'outline';
    
    return 'secondary';
  };

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Pedidos Unificados</h1>
            <p className="text-muted-foreground">Gestão centralizada de pedidos de todas as origens</p>
          </div>
          <Button>
            <Download className="h-4 w-4 mr-2" />
            Exportar
          </Button>
        </div>
      </div>

      {/* Filtros */}
      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4"> {/* Ajustado para 6 colunas */}
            <div className="space-y-2 col-span-2"> {/* Expandido para 2 colunas */}
              <Label htmlFor="search">Buscar</Label>
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="search"
                  placeholder="Número, cliente, ID externo..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>
            
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={selectedStatus} onValueChange={setSelectedStatus}>
                <SelectTrigger>
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  {statusOptions.map((status) => (
                    <SelectItem key={status.id} value={status.nome}>
                      {status.nome}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label>Origem</Label>
              <Select value={selectedOrigin} onValueChange={setSelectedOrigin}>
                <SelectTrigger>
                  <SelectValue placeholder="Todas" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="SHOPEE">Shopee</SelectItem>
                  <SelectItem value="BLING">Bling</SelectItem>
                  <SelectItem value="MANUAL">Manual</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Novo filtro de Canal de Venda */}
            <div className="space-y-2">
              <Label>Canal de Venda</Label>
              <Select value={selectedChannel} onValueChange={setSelectedChannel}>
                <SelectTrigger>
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  {canalVendaOptions.map((canal) => (
                    <SelectItem key={canal.id} value={String(canal.id)}>
                      {canal.nome}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="space-y-2">
              <Label>Data Início</Label>
              <Input 
                type="date" 
                value={dateRange.start} 
                onChange={(e) => setDateRange({...dateRange, start: e.target.value})} 
              />
            </div>
            
            <div className="space-y-2">
              <Label>Data Fim</Label>
              <Input 
                type="date" 
                value={dateRange.end} 
                onChange={(e) => setDateRange({...dateRange, end: e.target.value})} 
              />
            </div>
          </div>
          
          <div className="mt-4 flex justify-end">
            <Button onClick={handleFilterApply} disabled={loading}>
              <Filter className="h-4 w-4 mr-2" />
              {loading ? 'Carregando...' : 'Aplicar Filtros'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Resumo de Pedidos */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Total de Pedidos</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalOrders}</div> {/* Usar totalOrders do backend */}
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Pedidos Pendentes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{orders.filter(o => o.situacao_pedido?.nome === 'PENDENTE').length}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Pedidos Pagos</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{orders.filter(o => o.situacao_pedido?.nome === 'PAGO').length}</div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Valor Total</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatCurrency(orders.reduce((sum, order) => sum + (order.total_pedido || 0), 0))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Lista de Pedidos */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Pedidos</span>
            <span className="text-sm text-muted-foreground">
              Mostrando <strong>{orders.length}</strong> de <strong>{totalOrders}</strong> pedidos
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Número</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Data</TableHead>
                  <TableHead>Origem / Canal</TableHead> {/* Atualizado para incluir Canal */}
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="w-16">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.length > 0 ? (
                  orders.map((order) => (
                    <TableRow key={order.id}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          <Package className="h-4 w-4 text-muted-foreground" />
                          {order.numero_pedido}
                          {order.codigo_pedido_externo && (
                            <span className="text-xs text-muted-foreground" title="Código Externo">
                              ({order.codigo_pedido_externo})
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{order.cliente_nome || 'N/A'}</div>
                        <div className="text-xs text-muted-foreground">{order.cliente_documento || 'Sem doc.'}</div>
                      </TableCell>
                      <TableCell>{formatDate(order.data_venda)}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="uppercase mr-2">
                          {order.origem}
                        </Badge>
                        {order.canal_venda && (
                            <Badge variant="secondary" className="normal-case">
                                {order.canal_venda.nome}
                            </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={getStatusColor(order.situacao_pedido?.nome)}> {/* Usar situacao_pedido.nome */}
                          {order.situacao_pedido?.nome || 'PENDENTE'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatCurrency(order.total_pedido)}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm">
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem>
                              <Eye className="h-4 w-4 mr-2" />
                              Visualizar Detalhes
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                              <Calendar className="h-4 w-4 mr-2" />
                              Alterar Data
                            </DropdownMenuItem>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <DropdownMenuItem onSelect={(e) => e.preventDefault()}>
                                  Alterar Status
                                </DropdownMenuItem>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent>
                                {statusOptions
                                  .filter(status => status.nome !== order.situacao_pedido?.nome)
                                  .map(status => (
                                    <DropdownMenuItem 
                                      key={status.id} 
                                      onClick={() => handleStatusChange(order.id, status.nome)}
                                    >
                                      {status.nome}
                                    </DropdownMenuItem>
                                  ))
                                }
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={7} className="h-24 text-center">
                      {loading ? 'Carregando pedidos...' : 'Nenhum pedido encontrado'}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div className="mt-4 flex justify-between items-center px-2 py-4">
            <div className="text-sm text-muted-foreground">
              Mostrando <strong>{(currentPage - 1) * perPage + 1}</strong> a <strong>{Math.min(currentPage * perPage, totalOrders)}</strong> de <strong>{totalOrders}</strong> pedidos
            </div>
            <div className="flex items-center space-x-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                disabled={currentPage === 1 || loading}
              >
                Anterior
              </Button>
              <div className="text-sm font-medium">
                Página {currentPage} de {Math.ceil(totalOrders / perPage) || 1}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(prev => prev + 1)}
                disabled={currentPage >= Math.ceil(totalOrders / perPage) || loading}
              >
                Próximo
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default UnifiedOrdersPage;