import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from "@/components/ui/table";
import { 
  Card, CardContent, CardHeader, CardTitle 
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { 
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue 
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Search, Filter, Download, Eye, MoreHorizontal,
  Package, Calendar, CheckCircle2, AlertCircle, ShoppingCart, Zap,
  Phone, Mail, User
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const UnifiedOrdersPage = () => {
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [selectedOrigin, setSelectedOrigin] = useState('all');
  const [selectedChannel, setSelectedChannel] = useState('all');
  const [dateRange, setDateRange] = useState({ start: '', end: '' });
  const [statusOptions, setStatusOptions] = useState([]);
  const [canalVendaOptions, setCanalVendaOptions] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalOrders, setTotalOrders] = useState(0);
  const perPage = 50;
  
  // Novos filtros para consolidação
  const [hasDemanda, setHasDemanda] = useState('all'); // 'all', 'true', 'false'
  const [deliveryDateRange, setDeliveryDateRange] = useState({ start: '', end: '' });

  useEffect(() => {
    fetchStatusOptions();
    fetchCanalVendaOptions();
    fetchOrders();
  }, [currentPage, selectedStatus, selectedOrigin, selectedChannel]);

  const fetchStatusOptions = async () => {
    try {
      const response = await fetch('/api/v2/order/status-options');
      const data = await response.json();
      if (data.success) setStatusOptions(data.data.status_options);
    } catch (error) {
      console.error("Erro ao buscar status:", error);
    }
  };

  const fetchCanalVendaOptions = async () => {
    try {
      const response = await fetch('/api/v2/consolidar-base/plataformas');
      const data = await response.json();
      if (data.success) setCanalVendaOptions(data.data);
    } catch (error) {
      console.error("Erro ao buscar canais:", error);
    }
  };

  const fetchOrders = async () => {
    setLoading(true);
    try {
      // Construir query params para o endpoint avançado
      const params = new URLSearchParams();
      params.append('page', currentPage);
      params.append('limit', perPage);
      
      if (selectedStatus !== 'all') params.append('status_id', selectedStatus);
      if (selectedChannel !== 'all') params.append('canal_venda_id', selectedChannel);
      if (hasDemanda !== 'all') params.append('has_demanda', hasDemanda);
      if (deliveryDateRange.start) params.append('delivery_start', deliveryDateRange.start);
      if (deliveryDateRange.end) params.append('delivery_end', deliveryDateRange.end);
      if (searchTerm) params.append('search', searchTerm);
      
      const response = await fetch(`/api/v2/order/list-advanced?${params.toString()}`);
      const data = await response.json();
      
      if (data.success) {
        setOrders(data.data.orders);
        setTotalOrders(data.data.total);
      } else {
        toast.error(data.message || "Erro ao buscar pedidos");
      }
    } catch (error) {
      console.error("Erro ao buscar pedidos:", error);
      toast.error("Erro de conexão");
    } finally {
      setLoading(false);
    }
  };

  const handleFilterApply = () => {
    setCurrentPage(1);
    fetchOrders();
  };

  const handleStatusChange = async (orderId, newStatusName) => {
    // Implementação simplificada de troca de status
    toast.info(`Alterando status para ${newStatusName}...`);
  };

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
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
  };

  const getStatusColor = (statusName) => {
    if (!statusName) return 'secondary';
    const s = statusName.toUpperCase();
    // Novos status de sincronização
    if (s.includes('PROCESSANDO') || s.includes('EM PRODUCAO') || s.includes('EM_PRODUCAO')) return 'default'; // Azul (Processando/Em Produção)
    if (s.includes('PRONTO') && s.includes('ENVIO')) return 'success'; // Verde (Pronto para Envio)
    // Status existentes
    if (s.includes('PAGO')) return 'default';
    if (s.includes('CANCELADO')) return 'destructive';
    if (s.includes('ENTREGUE')) return 'success';
    if (s.includes('ENVIADO')) return 'outline';
    return 'secondary';
  };

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Vendas Centralizadas</h1>
          <p className="text-muted-foreground text-sm">Base única de pedidos integrados</p>
        </div>
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" /> Exportar
        </Button>
      </div>

      <Card className="mb-6">
        <CardContent className="pt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
            <div className="lg:col-span-2 space-y-2">
              <Label>Buscar</Label>
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Número, Cliente, Marketplace ID..."
                  value={searchTerm}
                  onChange={e => setSearchTerm(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={selectedStatus} onValueChange={setSelectedStatus}>
                <SelectTrigger><SelectValue placeholder="Todos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  {statusOptions.map(s => <SelectItem key={s.id} value={s.nome}>{s.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Demanda</Label>
              <Select value={hasDemanda} onValueChange={setHasDemanda}>
                <SelectTrigger><SelectValue placeholder="Todos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  <SelectItem value="true">Com demanda</SelectItem>
                  <SelectItem value="false">Sem demanda</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Entrega Início</Label>
              <Input type="date" value={deliveryDateRange.start} onChange={e => setDeliveryDateRange({...deliveryDateRange, start: e.target.value})} />
            </div>
            <div className="space-y-2">
              <Label>Entrega Fim</Label>
              <Input type="date" value={deliveryDateRange.end} onChange={e => setDeliveryDateRange({...deliveryDateRange, end: e.target.value})} />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4 mt-4">
            <div className="space-y-2">
              <Label>Plataforma</Label>
              <Select value={selectedOrigin} onValueChange={setSelectedOrigin}>
                <SelectTrigger><SelectValue placeholder="Todas" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas</SelectItem>
                  <SelectItem value="SHOPEE">Shopee</SelectItem>
                  <SelectItem value="BLING">Bling</SelectItem>
                  <SelectItem value="MARKETPLACE">Marketplace</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Canal de Venda</Label>
              <Select value={selectedChannel} onValueChange={setSelectedChannel}>
                <SelectTrigger><SelectValue placeholder="Todos" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  {canalVendaOptions.map(c => <SelectItem key={c.id} value={String(c.id)}>{c.nome}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Data Início</Label>
              <Input type="date" value={dateRange.start} onChange={e => setDateRange({...dateRange, start: e.target.value})} />
            </div>
            <div className="space-y-2 flex flex-col justify-end pb-0.5">
               <Button onClick={handleFilterApply} disabled={loading} className="w-full">
                 <Filter className="h-4 w-4 mr-2" /> Filtrar
               </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="py-4">
          <div className="flex justify-between items-center">
            <CardTitle className="text-lg">Resultados ({totalOrders})</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="rounded-none border-x-0 border-b">
            <Table>
              <TableHeader className="bg-muted/30">
                <TableRow>
                  <TableHead className="w-[180px]">Número</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Data</TableHead>
                  <TableHead>Origem / Canal</TableHead>
                  <TableHead>Status Pedido</TableHead>
                  <TableHead>Demanda</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <TableRow><TableCell colSpan={8} className="text-center py-10">Carregando...</TableCell></TableRow>
                ) : orders.length > 0 ? (
                  orders.map((order) => {
                    const hasDemands = order.demandas && order.demandas.length > 0;
                    const productionStatus = hasDemands ? order.demandas[0].status : 'NÃO INICIADA';
                    
                    // Número principal: sempre numero_pedido (do Bling quando existir)
                    const numeroExibicao = order.numero_pedido || '-';
                    
                    // IDs únicos de plataformas para as pills (evitar duplicatas)
                    const plataformasUnicas = order.integracoes 
                      ? [...new Set(order.integracoes.map(i => i.plataforma?.toUpperCase()))]
                      : [];

                    return (
                      <TableRow key={order.id} className="hover:bg-muted/20 cursor-pointer" onClick={() => navigate(`/pedidos/${order.id}`)}>
                        <TableCell className="font-bold py-4" onClick={(e) => e.stopPropagation()}>
                          <div className="flex flex-col">
                            <div className="flex items-center gap-1 text-blue-700">
                                <Package className="h-3 w-3" />
                                <button 
                                  className="hover:underline font-semibold"
                                  onClick={() => navigate(`/pedidos/${order.id}`)}
                                >
                                  {numeroExibicao}
                                </button>
                            </div>
                            {/* Exibe codigo_pedido_externo apenas se for diferente do numero_pedido */}
                            {order.codigo_pedido_externo && 
                             order.codigo_pedido_externo !== numeroExibicao && 
                             order.codigo_pedido_externo !== order.numero_pedido && (
                              <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[150px]">
                                {order.codigo_pedido_externo}
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium text-sm">{order.cliente_nome || 'N/A'}</span>
                            <div className="flex gap-2 items-center text-[10px] text-muted-foreground mt-0.5">
                               {order.cliente_documento && <span>{order.cliente_documento}</span>}
                               {order.is_flex && (
                                   <Badge className="bg-amber-600 h-4 text-[8px] px-1 gap-0.5">
                                       <Zap className="w-2 h-2 fill-white" /> FLEX
                                   </Badge>
                               )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs">{formatDate(order.data_venda)}</TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {/* Pills de Integrações (únicas, sem duplicatas) */}
                            {plataformasUnicas.map((plataforma, idx) => {
                              const plataformaLower = plataforma?.toLowerCase();
                              return (
                                <Badge 
                                  key={idx} 
                                  variant="secondary" 
                                  className="text-[9px] h-4 bg-slate-100 border-slate-200 capitalize"
                                >
                                  {plataformaLower === 'bling' ? 'Bling' : 
                                   plataformaLower === 'shopee' ? 'Shopee' :
                                   plataformaLower === 'amazon' ? 'Amazon' :
                                   plataformaLower === 'mercadolivre' ? 'Mercado Livre' :
                                   plataformaLower === 'shein' ? 'Shein' :
                                   plataforma}
                                </Badge>
                              );
                            })}
                            {order.canal_venda && (
                                <Badge variant="outline" className="text-[9px] h-4 border-blue-200 text-blue-700">
                                    {order.canal_venda.nome}
                                </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusColor(order.situacao_pedido?.nome)} className="text-[10px] h-5">
                            {order.situacao_pedido?.nome || 'PENDENTE'}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {order.demandas && order.demandas.length > 0 ? (
                            <div className="flex items-center gap-2">
                              <CheckCircle2 className="w-4 h-4 text-green-600" />
                              <Badge
                                variant="secondary"
                                className="text-[10px] h-5 cursor-pointer hover:bg-blue-100"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigate(`/producao/demanda/${order.demandas[0].demanda_id}/dashboard`);
                                }}
                              >
                                {order.demandas[0].status?.replace('_', ' ') || 'Em Produção'}
                              </Badge>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 text-muted-foreground">
                              <AlertCircle className="w-4 h-4" />
                              <span className="text-xs">Sem demanda</span>
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-bold text-sm">
                          {formatCurrency(order.total_pedido)}
                        </TableCell>
                        <TableCell>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" className="h-8 w-8"><MoreHorizontal className="h-4 w-4" /></Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem className="text-xs"><Eye className="h-3 w-3 mr-2" /> Ver Detalhes</DropdownMenuItem>
                              {hasDemands && (
                                <DropdownMenuItem className="text-xs" onClick={() => window.location.href=`/producao/demanda/${order.demandas[0].id}/dashboard`}>
                                  <Zap className="h-3 w-3 mr-2 text-amber-500" /> Ver Produção
                                </DropdownMenuItem>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    );
                  })
                ) : (
                  <TableRow><TableCell colSpan={8} className="text-center py-20 text-muted-foreground italic">Nenhum pedido encontrado</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          
          <div className="p-4 flex justify-between items-center text-xs text-muted-foreground">
             <div>Página {currentPage}</div>
             <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setCurrentPage(p => Math.max(1, p-1))} disabled={currentPage === 1}>Anterior</Button>
                <Button variant="outline" size="sm" onClick={() => setCurrentPage(p => p+1)} disabled={orders.length < perPage}>Próximo</Button>
             </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default UnifiedOrdersPage;
