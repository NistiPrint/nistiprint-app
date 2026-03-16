import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import ProductionService from '@/services/ProductionService';
import { format } from 'date-fns';
import { ChevronDown, ChevronRight, Eye, History, LayoutGrid, LayoutList, Loader2, Minus, Package, Plus, Search, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const ControleProducaoPage = ({tipo}) => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState(() => localStorage.getItem('producaoMiolosView') || 'list');
  const [filter, setFilter] = useState('');
  const [selectedDate, setSelectedDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [totalActive, setTotalActive] = useState(0);
  
  // Controle de Reversão de Log
  const [revertDialogOpen, setRevertDialogOpen] = useState(false);
  const [logToRevert, setLogToRevert] = useState(null);
  const [revertStock, setRevertStock] = useState(true);
  const [isReverting, setIsReverting] = useState(false);

  const [activeTab, setActiveTab] = useState('estoque'); // Adiciona estado para controle das abas
  const [capaSubTab, setCapaSubTab] = useState('impressao'); // Nova sub-aba para Capas: 'impressao' ou 'fechamento'
  const [demandSubTab, setDemandSubTab] = useState(tipo === 'miolo' ? 'miolo' : 'capa');


  // Estados para a visão de demandas
  const [mioloDemandSummary, setMioloDemandSummary] = useState([]);
  const [mioloDemandLoading, setMioloDemandLoading] = useState(false);
  const [capaDemandInfo, setCapaDemandInfo] = useState([]);
  const [capaDemandLoading, setCapaDemandLoading] = useState(false);
  const [activeDemands, setActiveDemands] = useState([]);
  const [activeDemandsLoading, setActiveDemandsLoading] = useState(false);
  const [mioloDemandModalOpen, setMioloDemandModalOpen] = useState(false);
  const [capaDemandModalOpen, setCapaDemandModalOpen] = useState(false);

  // Estados para Distribuição de Saída
  const [distributionModalOpen, setDistributionModalOpen] = useState(false);
  const [selectedProductForDistribution, setSelectedProductForDistribution] = useState(null);
  const [pendingDemandsForProduct, setPendingDemandsForProduct] = useState([]);
  const [distributionQuantities, setDistributionQuantities] = useState({});
  const [isDistributing, setIsDistributing] = useState(false);
  const [distributionLoading, setDistributionLoading] = useState(false);

  const [selectedDemandaId, setSelectedDemandaId] = useState(null);

  // Estados para Logs
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [productLogs, setProductLogs] = useState([]);
  const [selectedProductForLog, setSelectedProductForLog] = useState(null);
  const [logLoading, setLogLoading] = useState(false);

  // Estado para expandir demandas no consolidado de miolo
  const [expandedMiolos, setExpandedMiolos] = useState({});

  // Inputs state for quantities
  const [inputs, setInputs] = useState({});
  
  // Títulos dinâmicos considerando sub-aba
  const getPageTitle = () => {
    if (tipo === 'miolo') return 'Controle de Produção de Miolos';
    return capaSubTab === 'impressao' ? 'Impressão de Capas' : 'Fechamento de Capas';
  };
  
  const pageTitle = getPageTitle();
  const totalLabel = tipo === 'miolo' ? 'Total de Miolos Ativos' : 
                    capaSubTab === 'impressao' ? 'Total de Capas p/ Imprimir' : 'Total de Capas p/ Fechar';

  const fetchData = async () => {
    setLoading(true);
    try {
      // Se for capa e a sub-aba for fechamento, passamos o parâmetro correto para o service
      const subtipo = (tipo === 'capa' && capaSubTab === 'fechamento') ? 'capa_acabada' : tipo;
      const data = await ProductionService.getControleData(subtipo);
      
      if (data.success) {
        setProducts(data.products || []);
        setTotalActive(data.total_active_cores || 0);
        setSelectedDate(data.selected_date || format(new Date(), 'yyyy-MM-dd'));
      } else {
        toast.error(data.error || 'Erro ao carregar dados.');
        setProducts([]);
        setTotalActive(0);
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao carregar dados.';
      toast.error(errorMessage);
      console.error('ControleProducaoPage - Fetch Error:', error);
      setProducts([]);
      setTotalActive(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [tipo, activeTab, capaSubTab]); // Adicionado capaSubTab para recarregar ao trocar de sub-aba

  // Resetar sub-aba de demandas quando o tipo da página mudar
  useEffect(() => {
    setDemandSubTab(tipo === 'miolo' ? 'miolo' : 'capa');
  }, [tipo]);

  // Carregar dados de demanda quando a aba de demandas for selecionada ou o subtab mudar
  useEffect(() => {
    if (activeTab === 'demandas') {
      if (demandSubTab === 'lista') {
        handleActiveDemandsClick();
      } else if (demandSubTab === 'miolo') {
        handleMioloDemandClick();
      } else if (demandSubTab === 'capa') {
        handleCapaDemandClick();
      }
    }
  }, [activeTab, demandSubTab, tipo]);

  const handleInputChange = (productId, value) => {
    setInputs(prev => ({ ...prev, [productId]: value }));
  };

  const handleProduction = async (productId) => {
    const quantity = parseInt(inputs[productId]);
    if (!quantity || quantity <= 0) {
      toast.warning('Insira uma quantidade válida.');
      return;
    }

    try {
      // Determinar o campo de progresso baseado no contexto
      let field = null;
      if (tipo === 'miolo') field = 'miolos_prontos_retirada_qtd';
      else if (capaSubTab === 'impressao') field = 'capas_impressas_qtd';
      else if (capaSubTab === 'fechamento') field = 'capas_produzidas_qtd';

      // Tela de Controle de Produção: processamento SÍNCRONO (tempo real)
      const result = await ProductionService.registerProduction({
        product_id: productId,
        quantity: quantity,
        date: selectedDate,
        field: field,
        sincrono: true // Processamento imediato, sem fila
      });


      if (result.success) {
        toast.success(result.message);
        if (result.warning) {
          toast.warning(result.warning, { duration: 6000 });
        }
        setInputs(prev => ({ ...prev, [productId]: '' }));
        updateProductState(productId, result);
      } else {
        toast.error(result.error || 'Erro ao registrar produção.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao registrar produção.';
      toast.error(errorMessage);
      console.error('Erro ao registrar produção:', error);
    }
  };

  const handleRemovalClick = async (product) => {
    const totalToDistribute = parseFloat(inputs[product.id]);
    if (!totalToDistribute || totalToDistribute <= 0) {
      toast.warning('Insira uma quantidade válida no campo Qtd antes de clicar em saída.');
      return;
    }

    setSelectedProductForDistribution({ ...product, totalToDistribute });
    setDistributionModalOpen(true);
    setDistributionQuantities({});
    setSelectedDemandaId(null);
    setDistributionLoading(true);
    
    try {
      // Buscar TODAS as demandas ativas para o usuário selecionar
      const response = await fetch('/api/v2/demanda_producao/');
      const data = await response.json();
      if (data.success) {
        // Filtrar apenas demandas em andamento
        const activeStatuses = ['Pendente', 'Em Produção', 'Em Andamento', 'Criada', 'AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'];
        const active = data.demandas.filter(d => activeStatuses.includes(d.status));
        setPendingDemandsForProduct(active);
      } else {
        toast.error(data.message);
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao buscar demandas.';
      toast.error(errorMessage);
    } finally {
      setDistributionLoading(false);
    }
  };

  const handleDistributionSubmit = async (manualDists = null) => {
    const distsToUse = manualDists || distributionQuantities;
    const distributions = Object.entries(distsToUse)
      .filter(([_, qty]) => qty > 0)
      .map(([itemId, qty]) => ({ item_id: itemId, quantidade: qty }));

    if (distributions.length === 0) {
      toast.warning('Nenhuma quantidade alocada.');
      return;
    }

    const totalDistributed = distributions.reduce((sum, d) => sum + d.quantidade, 0);
    // Margem de erro para float
    if (totalDistributed > selectedProductForDistribution.totalToDistribute + 0.0001) {
      toast.error(`A quantidade total distribuída (${totalDistributed}) excede a quantidade de saída informada (${selectedProductForDistribution.totalToDistribute}).`);
      return;
    }

    setIsDistributing(true);
    try {
      // Tela de Controle de Produção: processamento SÍNCRONO (tempo real)
      const result = await ProductionService.registerRemoval({
        product_id: selectedProductForDistribution.id,
        quantity: totalDistributed,
        date: selectedDate,
        distributions: distributions,
        demanda_id: manualDists ? selectedDemandaId : selectedDemandaId,
        sincrono: true // Processamento imediato, sem fila
      });

      if (result.success) {
        toast.success(result.message);
        setDistributionModalOpen(false);
        setInputs(prev => ({ ...prev, [selectedProductForDistribution.id]: '' }));
        
        // Update product state with new daily removal
        setProducts(prevProducts => prevProducts.map(p => {
          if (p.id === selectedProductForDistribution.id) {
            const oldStock = p.stock_details.quantidade || 0;
            const oldAvail = p.stock_details.quantidade_disponivel || 0;
            return {
              ...p,
              quantity_removed_today: result.new_daily_removed,
              stock_details: {
                ...p.stock_details,
                quantidade: oldStock - totalDistributed,
                quantidade_disponivel: oldAvail - totalDistributed
              }
            };
          }
          return p;
        }));
      } else {
        toast.error(result.error || 'Erro ao registrar saída distribuída.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao registrar saída distribuída.';
      toast.error(errorMessage);
    } finally {
      setIsDistributing(false);
    }
  };

  const handleLogClick = async (product) => {
    setSelectedProductForLog(product);
    setLogModalOpen(true);
    setLogLoading(true);
    try {
      const data = await ProductionService.getLogs(product.id, selectedDate);
      if (data.success) {
        setProductLogs(data.logs || []);
      } else {
        toast.error(data.error || 'Erro ao carregar logs.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao carregar logs.';
      toast.error(errorMessage);
    } finally {
      setLogLoading(false);
    }
  };

  const handleRevertLog = (logId) => {
    setLogToRevert(logId);
    setRevertStock(true);
    setRevertDialogOpen(true);
  };

  const confirmRevertLog = async () => {
    setIsReverting(true);
    try {
      const result = await ProductionService.deleteLog(logToRevert, revertStock);
      if (result.success) {
        toast.success(result.message);
        setRevertDialogOpen(false);
        // Refresh logs
        handleLogClick(selectedProductForLog);
        // Update product totals in main list
        updateProductState(selectedProductForLog.id, result);
      } else {
        toast.error(result.error || 'Erro ao excluir lançamento.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao excluir lançamento.';
      toast.error(errorMessage);
    } finally {
      setIsReverting(false);
    }
  };

  const toggleMioloExpansion = (id) => {
    setExpandedMiolos(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const updateProductState = (productId, result) => {
    setProducts(prevProducts => prevProducts.map(p => {
      if (p.id === productId) {
        // Update stock details with available quantity if provided, otherwise fallback to physical stock
        const newAvailable = result.new_stock_available !== undefined ? result.new_stock_available : result.new_stock;
        
        return {
          ...p,
          quantity_produced_today: result.new_daily_produced,
          quantity_removed_today: result.new_daily_removed,
          stock_details: { 
            ...p.stock_details, 
            quantidade: result.new_stock,
            quantidade_disponivel: newAvailable
          } 
        };
      }
      return p;
    }));
  };






  const handleMioloDemandClick = async () => {
    setMioloDemandLoading(true);
    try {
      const data = await ProductionService.getMioloDemandSummary();
      if (data.success) {
        setMioloDemandSummary(data.summary || {});
      } else {
        toast.error(data.error);
        setMioloDemandSummary([]);
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao carregar resumo da demanda de miolos.';
      toast.error(errorMessage);
      console.error('Erro ao carregar resumo da demanda de miolos:', error);
      setMioloDemandSummary([]);
    } finally {
      setMioloDemandLoading(false);
    }
  };

  const handleCapaDemandClick = async () => {
    setCapaDemandLoading(true);
    try {
      const data = await ProductionService.getCapaDemandInfo();
      if (data.success) {
        setCapaDemandInfo(data.items || []);
      } else {
        toast.error(data.error);
        setCapaDemandInfo([]);
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao carregar informações da demanda de capas.';
      toast.error(errorMessage);
      console.error('Erro ao carregar informações da demanda de capas:', error);
      setCapaDemandInfo([]);
    } finally {
      setCapaDemandLoading(false);
    }
  };

  const handleActiveDemandsClick = async () => {
    setActiveDemandsLoading(true);
    try {
      const response = await fetch('/api/v2/demanda_producao/');
      const data = await response.json();

      if (data.success) {
        // Filtrar apenas as demandas ativas (não finalizadas, não coletadas)
        const activeStatuses = ['Pendente', 'Em Produção', 'Em Andamento', 'Criada', 'AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL'];
        const active = data.demandas.filter(d => activeStatuses.includes(d.status));
        setActiveDemands(active || []);
      } else {
        toast.error(data.message || 'Erro ao carregar demandas ativas.');
        setActiveDemands([]);
      }
    } catch (error) {
      const errorMessage = error.message || 'Erro de comunicação com o servidor.';
      toast.error(errorMessage);
      console.error('Erro ao carregar demandas ativas:', error);
      setActiveDemands([]);
    } finally {
      setActiveDemandsLoading(false);
    }
  };

  const toggleView = (val) => {
    if (val) {
      setViewMode(val);
      localStorage.setItem('producaoMiolosView', val);
    }
  };

  const filteredProducts = useMemo(() => {
    if (!filter) return products;
    const lowerFilter = filter.toLowerCase();
    return products.filter(p => 
      p.name.toLowerCase().includes(lowerFilter) || 
      (p.sku && p.sku.toLowerCase().includes(lowerFilter))
    );
  }, [products, filter]);

  if (loading && products.length === 0) {
    return <div className="flex justify-center items-center h-screen"><Loader2 className="animate-spin h-8 w-8" /></div>;
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold">{pageTitle}</h1>
        <div className="flex gap-2">
          <ToggleGroup type="single" value={activeTab} onValueChange={setActiveTab} className="mr-2">
            <ToggleGroupItem value="estoque" aria-label="Estoque">
              Estoque
            </ToggleGroupItem>
            <ToggleGroupItem value="demandas" aria-label="Demandas">
              Demandas
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-4 flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="flex items-center gap-4 text-sm">
            <span><strong>Data:</strong> {format(new Date(selectedDate), 'dd/MM/yyyy')}</span>
            <Badge variant="secondary">{totalLabel}: {totalActive}</Badge>
          </div>
          <div className="flex items-center gap-2 w-full md:w-auto">
            <div className="relative w-full md:w-64">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input 
                placeholder="Filtrar por nome..." 
                className="pl-8" 
                value={filter} 
                onChange={(e) => setFilter(e.target.value)} 
              />
            </div>
            <ToggleGroup type="single" value={viewMode} onValueChange={toggleView}>
              <ToggleGroupItem value="list" aria-label="Lista"><LayoutList className="h-4 w-4" /></ToggleGroupItem>
              <ToggleGroupItem value="grid" aria-label="Grade"><LayoutGrid className="h-4 w-4" /></ToggleGroupItem>
            </ToggleGroup>
          </div>
        </CardContent>
      </Card>

      {/* Conteúdo baseado na aba selecionada */}
      {activeTab === 'estoque' ? (
        <>
          {/* Sub-abas para Capas */}
          {tipo === 'capa' && (
            <div className="flex gap-2 mb-4 bg-gray-50 p-2 rounded-lg border">
              <Button
                variant={capaSubTab === 'impressao' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setCapaSubTab('impressao')}
                className="flex-1 sm:flex-none"
              >
                1. Impressão
              </Button>
              <Button
                variant={capaSubTab === 'fechamento' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setCapaSubTab('fechamento')}
                className="flex-1 sm:flex-none"
              >
                2. Fechamento
              </Button>
            </div>
          )}

          {filteredProducts.length === 0 && !loading ? (
            <Card className="border-gray-200 bg-gray-50/50">
              <CardContent className="pt-6">
                <div className="text-center text-muted-foreground">
                  <Package className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>Nenhum {tipo === 'miolo' ? 'miolo' : 'capa'} encontrado{filter ? ` para "${filter}"` : ''}.</p>
                  {!filter && (
                    <p className="text-sm mt-2">
                      Verifique se a categoria de {tipo === 'miolo' ? 'miolos' : 'capas'} está configurada corretamente.
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : viewMode === 'list' ? (
            <Card>
              <CardContent className="p-0 overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Produto</TableHead>
                      <TableHead className="text-center">Atual</TableHead>
                      <TableHead className="text-center">Ideal</TableHead>
                      <TableHead className="text-center">Variação</TableHead>
                      <TableHead className="text-center">Impresso</TableHead>
                      <TableHead className="text-center">Saída</TableHead>
                      <TableHead style={{ width: '200px' }}>Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredProducts.map(product => {
                      const stock = product.stock_details?.quantidade_disponivel || 0;
                      const min = product.stock_min || 0;
                      const variation = stock - min;
                      return (
                        <TableRow key={product.id}>
                          <TableCell>
                            <div className="flex items-center">
                              <Link to={`/produtos/${product.id}/editar`} className="group mr-2">
                                <div className="font-bold text-blue-600 group-hover:underline">{product.name}</div>
                                <div className="text-xs text-muted-foreground group-hover:text-blue-500">{product.sku}</div>
                              </Link>
                            </div>
                          </TableCell>
                          <TableCell className="text-center">
                            <Popover>
                              <PopoverTrigger>
                                <span className={`text-lg font-bold cursor-pointer ${stock < min ? 'text-red-500' : 'text-green-600'}`}>
                                  {stock}
                                </span>
                              </PopoverTrigger>
                              <PopoverContent>
                                <div className="text-sm">
                                  <p>Físico: <Badge variant="outline">{product.stock_details?.quantidade || 0}</Badge></p>
                                  <p className="mt-1">Reservado: <Badge variant="secondary">{product.stock_details?.quantidade_reservada || 0}</Badge></p>
                                </div>
                              </PopoverContent>
                            </Popover>
                          </TableCell>
                          <TableCell className="text-center">{min}</TableCell>
                          <TableCell className="text-center">
                            <span className={variation < 0 ? 'text-red-500 font-bold' : ''}>{variation}</span>
                          </TableCell>
                          <TableCell className="text-center text-blue-600 font-bold">{product.quantity_produced_today || 0}</TableCell>
                          <TableCell className="text-center text-red-600 font-bold">{product.quantity_removed_today || 0}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <Input
                                type="number"
                                className="w-16 h-8 text-sm px-1"
                                placeholder="Qtd"
                                value={inputs[product.id] || ''}
                                onChange={(e) => handleInputChange(product.id, e.target.value)}
                              />
                              <Button size="sm" variant="outline" className="h-8 px-2 text-green-600 border-green-200 hover:bg-green-50" title="Entrada" onClick={() => handleProduction(product.id)}>
                                <Plus className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="outline" className="h-8 px-2 text-red-600 border-red-200 hover:bg-red-50" title="Saída" onClick={() => handleRemovalClick(product)}>
                                <Minus className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="ghost" className="h-8 px-2" title="Log" onClick={() => handleLogClick(product)}>
                                <History className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {filteredProducts.map(product => {
                 const stock = product.stock_details?.quantidade_disponivel || 0;
                 const min = product.stock_min || 0;
                 const variation = stock - min;
                 return (
                  <Card key={product.id} className="hover:shadow-md transition-shadow">
                    <CardContent className="p-4 flex flex-col h-full justify-between">
                       <div className="mb-2">
                         <div className="flex items-center">
                           <Link to={`/produtos/${product.id}/editar`} className="group mr-2">
                             <div className="font-bold text-sm truncate" title={product.name}>{product.name}</div>
                             <div className="text-xs text-muted-foreground truncate">{product.sku}</div>
                           </Link>
                         </div>
                       </div>

                       <div className="flex flex-col items-center my-2">
                          <div className="text-xs text-muted-foreground">Ideal: {min} | Var: <span className={variation < 0 ? 'text-red-500' : ''}>{variation}</span></div>
                          <Popover>
                            <PopoverTrigger>
                               <div className={`text-3xl font-bold cursor-pointer my-1 ${stock < min ? 'text-red-500' : 'text-green-600'}`}>
                                 {stock}
                               </div>
                            </PopoverTrigger>
                            <PopoverContent>
                              <div className="text-sm">
                                <p>Físico: <Badge variant="outline">{product.stock_details?.quantidade || 0}</Badge></p>
                                <p className="mt-1">Reservado: <Badge variant="secondary">{product.stock_details?.quantidade_reservada || 0}</Badge></p>
                              </div>
                            </PopoverContent>
                          </Popover>
                       </div>

                       <div className="flex justify-between text-xs font-bold mb-3">
                          <span className="text-blue-600">Imp: {product.quantity_produced_today || 0}</span>
                          <span className="text-red-600">Sai: {product.quantity_removed_today || 0}</span>
                       </div>

                       <div className="flex items-center gap-1 mt-auto">
                          <Input
                            type="number"
                            className="w-full h-8 text-sm px-1"
                            placeholder="Qtd"
                            value={inputs[product.id] || ''}
                            onChange={(e) => handleInputChange(product.id, e.target.value)}
                          />
                          <Button size="sm" variant="outline" className="h-8 w-8 p-0 text-green-600" onClick={() => handleProduction(product.id)}><Plus className="h-4 w-4" /></Button>
                          <Button size="sm" variant="outline" className="h-8 w-8 p-0 text-red-600" onClick={() => handleRemovalClick(product)}><Minus className="h-4 w-4" /></Button>
                          <Button size="sm" variant="ghost" className="h-8 w-8 p-0" onClick={() => handleLogClick(product)}><History className="h-4 w-4" /></Button>
                       </div>
                    </CardContent>
                  </Card>
                 );
              })}
            </div>
          )}
        </>
      ) : (
        /* Visão de Demandas */
        <Card>
          <CardContent className="p-4">
            {/* Abas para diferentes visualizações de demandas */}
            <div className="flex gap-2 mb-4">
              <Button
                variant={demandSubTab === 'lista' ? 'default' : 'outline'}
                onClick={() => setDemandSubTab('lista')}
              >
                Demandas Ativas
              </Button>
              {tipo === 'miolo' && (
                <Button
                  variant={demandSubTab === 'miolo' ? 'default' : 'outline'}
                  onClick={() => setDemandSubTab('miolo')}
                >
                  Consolidado de Miolo
                </Button>
              )}
              {tipo === 'capa' && (
                <Button
                  variant={demandSubTab === 'capa' ? 'default' : 'outline'}
                  onClick={() => setDemandSubTab('capa')}
                >
                  Consolidado de Capa
                </Button>
              )}
            </div>

            {/* Conteúdo baseado na seleção */}
            {demandSubTab === 'lista' ? (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold">Demandas Ativas</h2>
                <div className="space-y-3">
                  {activeDemandsLoading ? (
                    <div className="flex justify-center"><Loader2 className="animate-spin" /></div>
                  ) : activeDemands.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      <p>Nenhuma demanda ativa encontrada.</p>
                      <p className="text-sm mt-2">Clique no botão acima para recarregar as informações.</p>
                    </div>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>ID</TableHead>
                          <TableHead>Nome</TableHead>
                          <TableHead>Canal</TableHead>
                          <TableHead>Data Entrega</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead className="text-center">Quantidade</TableHead>
                          <TableHead className="text-center">Ações</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {activeDemands.map((demanda) => (
                          <TableRow key={demanda.id}>
                            <TableCell className="font-mono">{demanda.id.toString().slice(-4)}</TableCell>
                            <TableCell className="font-medium">{demanda.nome}</TableCell>
                            <TableCell>{demanda.canal_venda_nome || '-'}</TableCell>
                            <TableCell>{format(new Date(demanda.data_entrega), 'dd/MM/yyyy')}</TableCell>
                            <TableCell>
                              <Badge
                                variant={
                                  (demanda.status === 'Em Produção' || demanda.status === 'EM_PRODUCAO') ? 'default' :
                                  (demanda.status === 'Pendente' || demanda.status === 'AGUARDANDO') ? 'secondary' :
                                  (demanda.status === 'Em Andamento' || demanda.status === 'COLETA_PARCIAL') ? 'outline' :
                                  'destructive'
                                }
                              >
                                {demanda.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-center font-bold">{demanda.total_itens || 0}</TableCell>
                            <TableCell className="text-center">
                              <Link to={`/producao/demanda/${demanda.id}/dashboard`}>
                                <Button variant="outline" size="sm">
                                  <Eye className="h-4 w-4 mr-1" />
                                  Ver
                                </Button>
                              </Link>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              </div>
            ) : demandSubTab === 'miolo' ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <h2 className="text-xl font-semibold">Consolidado de Demandas por Miolo</h2>
                  <Button size="sm" variant="outline" onClick={handleMioloDemandClick} disabled={mioloDemandLoading}>
                    {mioloDemandLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
                    Atualizar
                  </Button>
                </div>
                <div className="space-y-3">
                  {mioloDemandLoading ? (
                    <div className="flex justify-center py-8"><Loader2 className="animate-spin h-8 w-8 text-blue-500" /></div>
                  ) : (!mioloDemandSummary || mioloDemandSummary.length === 0) ? (
                    <div className="text-center text-muted-foreground py-8">
                      <p>Nenhuma demanda encontrada.</p>
                      <Button className="mt-4" onClick={handleMioloDemandClick}>
                        Carregar Demandas
                      </Button>
                    </div>
                  ) : (
                    mioloDemandSummary.map((miolo) => {
                      const isExpanded = expandedMiolos[miolo.id || miolo.name];
                      return (
                        <div key={miolo.id || miolo.name} className="border rounded-lg overflow-hidden transition-all shadow-sm">
                          <div 
                            className={`flex justify-between items-center p-3 cursor-pointer hover:bg-gray-50 ${isExpanded ? 'bg-blue-50 border-b' : 'bg-white'}`}
                            onClick={() => toggleMioloExpansion(miolo.id || miolo.name)}
                          >
                            <div className="flex items-center gap-3">
                              {isExpanded ? <ChevronDown className="h-4 w-4 text-blue-600" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
                              <div className="font-bold text-blue-900">
                                {miolo.name}
                              </div>
                            </div>
                            <div className="flex items-center gap-4">
                              <Badge variant="outline" className="bg-white">
                                {miolo.demandas?.length || 0} demandas
                              </Badge>
                              <Badge variant="secondary" className="text-lg px-3 py-1 bg-blue-600 text-white">
                                {miolo.quantity}
                              </Badge>
                            </div>
                          </div>
                          
                          {isExpanded && (
                            <div className="bg-white p-0 animate-in slide-in-from-top-1 duration-200">
                              <Table>
                                <TableHeader className="bg-gray-50">
                                  <TableRow>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold">Demanda</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Entrega</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Faltam</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Total Item</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-right">Ação</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {miolo.demandas?.map((d, idx) => (
                                    <TableRow key={idx} className="hover:bg-gray-50/50">
                                      <TableCell className="py-2 font-medium text-xs">{d.demanda_nome}</TableCell>
                                      <TableCell className="py-2 text-center text-xs">{d.data_entrega ? format(new Date(d.data_entrega), 'dd/MM') : '-'}</TableCell>
                                      <TableCell className="py-2 text-center"><Badge className="bg-orange-100 text-orange-700 hover:bg-orange-100 border-none text-[10px]">{d.quantidade_faltante}</Badge></TableCell>
                                      <TableCell className="py-2 text-center text-xs text-muted-foreground">{d.quantidade_total}</TableCell>
                                      <TableCell className="py-2 text-right">
                                        <Link to={`/producao/demanda/${d.demanda_id}/dashboard`}>
                                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0"><Eye className="h-3.5 w-3.5" /></Button>
                                        </Link>
                                      </TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <h2 className="text-xl font-semibold">Consolidado de Demandas por Capa</h2>
                  <Button size="sm" variant="outline" onClick={handleCapaDemandClick} disabled={capaDemandLoading}>
                    {capaDemandLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
                    Atualizar
                  </Button>
                </div>
                <div className="space-y-3">
                  {capaDemandLoading ? (
                    <div className="flex justify-center py-8"><Loader2 className="animate-spin h-8 w-8 text-orange-500" /></div>
                  ) : capaDemandInfo.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      <p>Nenhuma informação de demanda encontrada.</p>
                      <Button className="mt-4" onClick={handleCapaDemandClick}>
                        Carregar Informações de Demanda
                      </Button>
                    </div>
                  ) : (
                    capaDemandInfo.map((capa) => {
                      const isExpanded = expandedMiolos[`capa_${capa.id}`];
                      return (
                        <div key={capa.id || capa.sku} className="border rounded-lg overflow-hidden transition-all shadow-sm">
                          <div 
                            className={`flex justify-between items-center p-3 cursor-pointer hover:bg-gray-50 ${isExpanded ? 'bg-orange-50 border-b' : 'bg-white'}`}
                            onClick={() => setExpandedMiolos(prev => ({ ...prev, [`capa_${capa.id}`]: !isExpanded }))}
                          >
                            <div className="flex items-center gap-3">
                              {isExpanded ? <ChevronDown className="h-4 w-4 text-orange-600" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
                              <div>
                                <div className="font-bold text-orange-900">{capa.name}</div>
                                <div className="text-xs text-orange-700/70">{capa.sku}</div>
                              </div>
                            </div>
                            <div className="flex items-center gap-4">
                              <Badge variant="outline" className="bg-white">
                                {capa.demandas?.length || 0} demandas
                              </Badge>
                              <Badge variant="secondary" className="text-lg px-3 py-1 bg-orange-600 text-white">
                                {capa.quantity}
                              </Badge>
                            </div>
                          </div>
                          
                          {isExpanded && (
                            <div className="bg-white p-0 animate-in slide-in-from-top-1 duration-200">
                              <Table>
                                <TableHeader className="bg-gray-50">
                                  <TableRow>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold">Demanda</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Entrega</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Faltam</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-center">Total Item</TableHead>
                                    <TableHead className="h-8 text-[10px] uppercase font-bold text-right">Ação</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {capa.demandas?.map((d, idx) => (
                                    <TableRow key={idx} className="hover:bg-gray-50/50">
                                      <TableCell className="py-2 font-medium text-xs">{d.demanda_nome}</TableCell>
                                      <TableCell className="py-2 text-center text-xs">{d.data_entrega ? format(new Date(d.data_entrega), 'dd/MM') : '-'}</TableCell>
                                      <TableCell className="py-2 text-center"><Badge className="bg-orange-100 text-orange-700 hover:bg-orange-100 border-none text-[10px]">{d.quantidade_faltante}</Badge></TableCell>
                                      <TableCell className="py-2 text-center text-xs text-muted-foreground">{d.quantidade_total}</TableCell>
                                      <TableCell className="py-2 text-right">
                                        <Link to={`/producao/demanda/${d.demanda_id}/dashboard`}>
                                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0"><Eye className="h-3.5 w-3.5" /></Button>
                                        </Link>
                                      </TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Modal de Distribuição de Saída */}
      <Dialog open={distributionModalOpen} onOpenChange={setDistributionModalOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex justify-between items-center pr-8">
              <span>Distribuir Saída: {selectedProductForDistribution?.sku}</span>
              <Badge variant="secondary" className="text-lg">Total: {selectedProductForDistribution?.totalToDistribute}</Badge>
            </DialogTitle>
            <div className="text-sm text-muted-foreground mt-1">
              {selectedProductForDistribution?.name}
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-hidden flex flex-col gap-4 py-4">
            <div className="bg-blue-50 p-3 rounded-lg border border-blue-100">
              <p className="text-sm text-blue-900 font-medium">Selecione a demanda para a qual deseja destinar estas <strong>{selectedProductForDistribution?.totalToDistribute}</strong> unidades.</p>
              <p className="text-[10px] text-blue-700 mt-1">A distribuição será feita automaticamente nos itens da demanda selecionada.</p>
            </div>

            <ScrollArea className="flex-1 border rounded-md">
              {distributionLoading ? (
                <div className="flex justify-center py-12"><Loader2 className="animate-spin h-8 w-8" /></div>
              ) : pendingDemandsForProduct.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">Nenhuma demanda ativa encontrada para este item com saldo pendente.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Demanda / Entrega</TableHead>
                      <TableHead className="text-center w-32">Saldo Necessário</TableHead>
                      <TableHead className="text-right w-24">Ação</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pendingDemandsForProduct.map(demanda => {
                      return (
                        <TableRow key={demanda.id} className="hover:bg-gray-50">
                          <TableCell className="py-3">
                            <div className="font-bold text-sm text-gray-900">{demanda.nome}</div>
                            <div className="text-[10px] text-muted-foreground uppercase">{format(new Date(demanda.data_entrega), 'dd/MM/yyyy')} - {demanda.canal_venda_nome}</div>
                          </TableCell>
                          <TableCell className="text-center py-3">
                            <Badge variant="outline">{demanda.total_itens} un totais</Badge>
                          </TableCell>
                          <TableCell className="text-right py-3">
                            <Button 
                              size="sm" 
                              onClick={async () => {
                                setSelectedDemandaId(demanda.id);
                                // 1. Buscar os itens detalhados desta demanda para validar
                                try {
                                  const res = await fetch(`/api/v2/demanda_producao/${demanda.id}`);
                                  const dData = await res.json();
                                  
                                  if (!dData.success || !dData.demanda?.itens) {
                                    toast.error("Erro ao validar itens da demanda.");
                                    return;
                                  }

                                  const itens = dData.demanda.itens;
                                  const isMiolo = tipo === 'miolo';
                                  
                                  // Filtrar itens que batem com o produto selecionado
                                  const matchingItens = itens.filter(i => {
                                    const targetId = isMiolo ? String(i.id_produto_miolo) : String(i.produto_id);
                                    return targetId === String(selectedProductForDistribution.id);
                                  });

                                  if (matchingItens.length === 0) {
                                    toast.error(`Esta demanda não contém este ${isMiolo ? 'miolo' : 'item'}.`);
                                    return;
                                  }

                                  // 2. Realizar distribuição automática Top-Down
                                  let remaining = selectedProductForDistribution.totalToDistribute;
                                  const dists = {};
                                  
                                  matchingItens.forEach(item => {
                                    if (remaining <= 0) return;
                                    const field = isMiolo ? 'miolos_prontos_retirada_qtd' : 'expedicao_capas_retiradas_qtd';
                                    const current = parseFloat(item[field] || 0);
                                    const needed = Math.max(0, parseFloat(item.quantidade_total) - current);
                                    
                                    if (needed > 0) {
                                      const allocation = Math.min(remaining, needed);
                                      dists[item.id] = allocation;
                                      remaining -= allocation;
                                    }
                                  });

                                  if (Object.keys(dists).length === 0) {
                                    toast.warning("Todos os itens deste tipo já estão concluídos nesta demanda.");
                                    return;
                                  }

                                  setDistributionQuantities(dists);
                                  handleDistributionSubmit(dists);
                                } catch (err) {
                                  const errorMessage = err.message || 'Erro ao processar demanda.';
                                  toast.error(errorMessage);
                                }
                              }}
                            >
                              Selecionar
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </ScrollArea>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDistributionModalOpen(false)}>Cancelar</Button>
            <Button 
              onClick={handleDistributionSubmit} 
              disabled={isDistributing || Object.values(distributionQuantities).reduce((a, b) => a + b, 0) === 0}
            >
              {isDistributing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Confirmar Distribuição
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Modal de Histórico/Logs */}
      <Dialog open={logModalOpen} onOpenChange={setLogModalOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Histórico de Produção do Dia</DialogTitle>
            <div className="text-sm text-muted-foreground">{selectedProductForLog?.name} ({selectedProductForLog?.sku})</div>
          </DialogHeader>
          
          <div className="py-4">
            {logLoading ? (
              <div className="flex justify-center py-8"><Loader2 className="animate-spin h-8 w-8" /></div>
            ) : productLogs.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">Nenhum lançamento encontrado para hoje.</div>
            ) : (
              <ScrollArea className="h-[300px] pr-4">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Hora</TableHead>
                      <TableHead>Tipo</TableHead>
                      <TableHead className="text-center">Qtd</TableHead>
                      <TableHead>Ref</TableHead>
                      <TableHead className="text-right">Ação</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {productLogs.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell className="text-xs">{log.time || (log.created_at ? format(new Date(log.created_at), 'HH:mm') : (log.timestamp && log.timestamp !== '-' ? log.timestamp.substring(0, 5) : '-'))}</TableCell>
                        <TableCell>
                          <Badge variant={log.quantity > 0 ? 'default' : 'destructive'} className="text-[10px] py-0">
                            {log.quantity > 0 ? 'ENTRADA' : 'SAÍDA'}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-center font-bold">{Math.abs(log.quantity)}</TableCell>
                        <TableCell className="text-[10px] font-mono text-muted-foreground">
                          {log.demanda_id ? `#${log.demanda_id.toString().slice(-4)}` : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button 
                            variant="ghost" 
                            size="icon" 
                            className="h-8 w-8 text-red-500 hover:text-red-700 hover:bg-red-50"
                            onClick={() => handleRevertLog(log.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            )}
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogModalOpen(false)}>Fechar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmação de Reversão de Log */}
      <AlertDialog open={revertDialogOpen} onOpenChange={setRevertDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar Exclusão de Lançamento</AlertDialogTitle>
            <AlertDialogDescription>
              Tem certeza que deseja excluir este registro de produção? Esta ação não pode ser desfeita.
            </AlertDialogDescription>
          </AlertDialogHeader>
          
          <div className="flex items-center space-x-2 py-4">
            <Checkbox 
              id="revertStock" 
              checked={revertStock} 
              onCheckedChange={setRevertStock} 
            />
            <div className="grid gap-1.5 leading-none">
              <Label htmlFor="revertStock" className="text-sm font-medium">
                Reverter movimentações de estoque
              </Label>
              <p className="text-xs text-muted-foreground">
                Se marcado, o sistema devolverá os insumos e retirará o produto final do estoque.
              </p>
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction 
              className="bg-red-600 hover:bg-red-700" 
              onClick={confirmRevertLog}
              disabled={isReverting}
            >
              {isReverting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              Confirmar Exclusão
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  );
};

export default ControleProducaoPage;
