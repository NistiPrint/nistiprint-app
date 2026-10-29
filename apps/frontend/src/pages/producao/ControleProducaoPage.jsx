import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import ProductionService from '@/services/ProductionService';
import ProductionPlanningViews from '@/components/producao/ProductionPlanningViews';
import { format } from 'date-fns';
import { Loader2, PackageMinus, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

const ControleProducaoPage = ({tipo}) => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [selectedDate, setSelectedDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  
  // Controle de Reversão de Log
  const [revertDialogOpen, setRevertDialogOpen] = useState(false);
  const [logToRevert, setLogToRevert] = useState(null);
  const [revertStock, setRevertStock] = useState(true);
  const [isReverting, setIsReverting] = useState(false);

  // A visão Previsão (só miolos) mora na URL (?vista=previsao) para poder ser compartilhada.
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTabState] = useState(() =>
    tipo === 'miolo' && searchParams.get('vista') === 'previsao' ? 'previsao' : 'demanda');
  const setActiveTab = (view) => {
    setActiveTabState(view);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (view === 'previsao') next.set('vista', 'previsao'); else next.delete('vista');
      return next;
    }, { replace: true });
  };
  const [planning, setPlanning] = useState(null);
  const [planningLoading, setPlanningLoading] = useState(false);
  const [planningError, setPlanningError] = useState('');
  const [includeSimulations, setIncludeSimulations] = useState(false);
  const [capaSubTab, setCapaSubTab] = useState('impressas'); // Sub-tab para capas: impressas vs acabadas
  const [previsao, setPrevisao] = useState(null);
  const [previsaoLoading, setPrevisaoLoading] = useState(false);
  const [previsaoError, setPrevisaoError] = useState('');
  const [previsaoFiltros, setPrevisaoFiltros] = useState({ horizonte: ['atrasado', 'hoje', 'sem_prazo'], incluirPronto: false });
  const [horizonte, setHorizonte] = useState(['atrasado', 'hoje', 'sem_prazo']);

  // Estados para Distribuição de Saída
  const [distributionModalOpen, setDistributionModalOpen] = useState(false);
  const [selectedProductForDistribution, setSelectedProductForDistribution] = useState(null);
  const [pendingDemandsForProduct, setPendingDemandsForProduct] = useState([]);
  const [distributionQuantities, setDistributionQuantities] = useState({});
  const [isDistributing, setIsDistributing] = useState(false);
  const [distributionLoading, setDistributionLoading] = useState(false);
  const pendingReservationOperation = useRef(null);
  const controlRequestId = useRef(0);
  const planningRequestId = useRef(0);
  const previsaoRequestId = useRef(0);

  const [selectedDemandaId, setSelectedDemandaId] = useState(null);

  // Saída avulsa: baixa imediata, sem demanda
  const [standaloneRemovalOpen, setStandaloneRemovalOpen] = useState(false);
  const [isRemovingStandalone, setIsRemovingStandalone] = useState(false);

  // Estados para Logs
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [productLogs, setProductLogs] = useState([]);
  const [selectedProductForLog, setSelectedProductForLog] = useState(null);
  const [logLoading, setLogLoading] = useState(false);

  // Inputs state for quantities
  const [inputs, setInputs] = useState({});
  
  const fetchData = useCallback(async () => {
    const requestId = ++controlRequestId.current;
    setLoading(true);
    try {
      // Determinar o tipo correto baseado no contexto
      let tipoParam = tipo;
      if (tipo === 'capa') {
        tipoParam = capaSubTab === 'impressas' ? 'capa' : 'capa_acabada';
      }
      
      const data = await ProductionService.getControleData(tipoParam);
      
      if (data.success) {
        if (requestId === controlRequestId.current) {
          setProducts(data.products || []);
          setSelectedDate(data.selected_date || format(new Date(), 'yyyy-MM-dd'));
        }
      } else {
        toast.error(data.error || 'Erro ao carregar dados.');
        if (requestId === controlRequestId.current) setProducts([]);
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao carregar dados.';
      toast.error(errorMessage);
      console.error('ControleProducaoPage - Fetch Error:', error);
      if (requestId === controlRequestId.current) setProducts([]);
    } finally {
      if (requestId === controlRequestId.current) setLoading(false);
    }
  }, [tipo, capaSubTab]);

  const fetchPlanning = useCallback(async () => {
    const requestId = ++planningRequestId.current;
    setPlanningLoading(true);
    setPlanningError('');
    setPlanning(null);
    try {
      const tipoParam = tipo === 'miolo' ? 'miolo' : capaSubTab === 'impressas' ? 'capa' : 'capa_acabada';
      const data = await ProductionService.getDemandPlanning(tipoParam, includeSimulations, { horizonte });
      if (!data.success) throw new Error(data.message || 'Erro ao carregar planejamento.');
      if (requestId === planningRequestId.current) setPlanning({ products: data.products || [], unmapped: data.unmapped || [] });
    } catch (error) {
      if (requestId === planningRequestId.current) {
        setPlanningError(error.response?.data?.message || error.message || 'Erro ao carregar planejamento.');
        setPlanning(null);
      }
    } finally {
      if (requestId === planningRequestId.current) setPlanningLoading(false);
    }
  }, [tipo, capaSubTab, includeSimulations, horizonte]);

  useEffect(() => {
    fetchData();
    fetchPlanning();
  }, [fetchData, fetchPlanning]);

  // Lazy: a consolidação dos lotes da Torre é mais cara que o resto da tela, então
  // só roda quando a visão Previsão está aberta (e a cada troca de filtro).
  const fetchPrevisao = useCallback(async () => {
    const requestId = ++previsaoRequestId.current;
    setPrevisaoLoading(true);
    setPrevisaoError('');
    try {
      const data = await ProductionService.getPrevisaoMiolos(previsaoFiltros);
      if (!data.success) throw new Error(data.error || 'Erro ao carregar a previsão de miolos.');
      if (requestId === previsaoRequestId.current) setPrevisao(data.data);
    } catch (error) {
      if (requestId === previsaoRequestId.current) {
        setPrevisaoError(error.response?.data?.error || error.message || 'Erro ao carregar a previsão de miolos.');
        setPrevisao(null);
      }
    } finally {
      if (requestId === previsaoRequestId.current) setPrevisaoLoading(false);
    }
  }, [previsaoFiltros]);

  useEffect(() => {
    if (tipo === 'miolo' && activeTab === 'previsao') fetchPrevisao();
  }, [tipo, activeTab, fetchPrevisao]);

  const handleInputChange = (productId, value) => {
    setInputs(prev => ({ ...prev, [productId]: value }));
  };

  const handleProduction = async (productId) => {
    const quantity = Number(inputs[productId]);
    if (!Number.isInteger(quantity) || quantity <= 0) {
      toast.warning('Insira uma quantidade inteira positiva.');
      return;
    }

    try {
      // [+] PRODUZ: dá entrada do produto no estoque e consome a BOM.
      // NÃO enviar `field` aqui. O `field` é o caminho de ALOCAÇÃO em demanda:
      // com ele a API desviava para processar_alocacao_avulsa_otimizado, que
      // gerava PROD_INT + CONS_INT no mesmo lote (saldo líquido zero) e o miolo
      // produzido nunca ficava disponível em estoque. A alocação é o [-].
      // Tela de Controle de Produção: processamento SÍNCRONO (tempo real)
      const result = await ProductionService.registerProduction({
        product_id: productId,
        quantity: quantity,
        date: selectedDate,
        sincrono: true // Processamento imediato, sem fila
      });


      if (result.success) {
        toast.success(result.message);
        if (result.warning) {
          toast.warning(result.warning, { duration: 6000 });
        }
        setInputs(prev => ({ ...prev, [productId]: '' }));
        updateProductState(productId, result);
        fetchData(); // Refresh data to show updated stock
        fetchPlanning();
      } else {
        toast.error(result.error || 'Erro ao registrar produção.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao registrar produção.';
      toast.error(errorMessage);
      console.error('Erro ao registrar produção:', error);
    }
  };

  const handleRemovalClick = async (product, allocation = {}) => {
    // Na visão Estoque os produtos vêm do planejamento com `product_id`;
    // no cadastro de estoque vêm com `id`. Normalize antes de ler o campo e
    // antes de seguir para os fluxos de reserva.
    const productId = product?.id ?? product?.product_id;
    const rawQuantity = allocation.quantity ?? inputs[productId];
    const totalToDistribute = Number(rawQuantity);
    if (rawQuantity === undefined || rawQuantity === null || rawQuantity === '' || !Number.isFinite(totalToDistribute) || totalToDistribute <= 0) {
      toast.warning('Insira uma quantidade válida no campo Qtd antes de clicar em saída.');
      return;
    }
    if (allocation.maxQuantity !== undefined && totalToDistribute > Number(allocation.maxQuantity)) {
      toast.warning(`A quantidade não pode exceder o pendente desta demanda (${allocation.maxQuantity}).`);
      return;
    }

    setSelectedProductForDistribution({ ...product, id: productId, totalToDistribute });
    setDistributionModalOpen(true);
    setDistributionQuantities({});
    setSelectedDemandaId(allocation.demandaId ? String(allocation.demandaId) : null);
    setDistributionLoading(true);
    
    try {
      // O cadastro ainda não é suficientemente consistente para filtrar por
      // vínculo de produto. Mostramos todas as demandas e os cenários salvos.
      const [realResponse, simulationsResponse] = await Promise.all([
        fetch('/api/v2/demanda_producao/'),
        fetch('/api/v2/demanda-simulacoes'),
      ]);
      const [realData, simulationsData] = await Promise.all([
        realResponse.json(), simulationsResponse.json(),
      ]);
      if (!realData.success) throw new Error(realData.message || 'Erro ao buscar demandas.');
      const real = (realData.demandas || []).map(d => ({ ...d, simulacao: false }));
      const simulations = simulationsData.success
        ? (simulationsData.data || []).map(d => ({ ...d, simulacao: true }))
        : [];
      const all = [...real, ...simulations]
        .filter(d => {
          const status = String(d.status ?? d.demanda_status ?? '').trim().toLocaleUpperCase('pt-BR');
          const name = String(d.nome ?? d.name ?? d.descricao ?? '').trim().toLocaleUpperCase('pt-BR');
          return status !== 'RASCUNHO' && status !== 'CANCELADO' && !name.startsWith('RASCUNHO ');
        })
        .filter(d => !allocation.demandaId || String(d.id) === String(allocation.demandaId));
      setPendingDemandsForProduct(all);
      if (!simulationsData.success) toast.warning('Não foi possível carregar as simulações. As demandas reais estão disponíveis.');
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao buscar demandas.';
      toast.error(errorMessage);
    } finally {
      setDistributionLoading(false);
    }
  };

  const handleDistributionSubmit = async (manualDists = null, demandId = selectedDemandaId) => {
    const distsToUse = manualDists || distributionQuantities;
    const distributions = Object.entries(distsToUse)
      .filter(([, qty]) => qty > 0)
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
      const reservationKey = `production-reservation:${selectedProductForDistribution.id}:${demandId || 'mixed'}`;
      const requestContent = JSON.stringify({
        product_id: selectedProductForDistribution.id,
        demanda_id: demandId,
        distributions,
        date: selectedDate,
      });
      let pending = pendingReservationOperation.current;
      try {
        const saved = JSON.parse(sessionStorage.getItem(reservationKey) || 'null');
        if (!pending && saved?.content === requestContent) pending = saved;
      } catch { /* sessão sem estado recuperável */ }
      if (!pending || pending.content !== requestContent) {
        pending = { content: requestContent, operation_id: crypto.randomUUID() };
        pendingReservationOperation.current = pending;
        sessionStorage.setItem(reservationKey, JSON.stringify(pending));
      }
      // Tela de Controle de Produção: processamento SÍNCRONO (tempo real)
      const result = await ProductionService.registerRemoval({
        product_id: selectedProductForDistribution.id,
        quantity: totalDistributed,
        date: selectedDate,
        distributions: distributions,
        demanda_id: demandId,
        sincrono: true, // Processamento imediato, sem fila
        operation_id: pending.operation_id,
      });

      if (result.success) {
        pendingReservationOperation.current = null;
        sessionStorage.removeItem(reservationKey);
        toast.success(result.message);
        setDistributionModalOpen(false);
        setInputs(prev => ({ ...prev, [selectedProductForDistribution.id]: '' }));
        
        // Alocação reserva o item: o DISPONÍVEL cai, o saldo físico não.
        // A baixa física só ocorre na reconciliação, após a finalização.
        setProducts(prevProducts => prevProducts.map(p => {
          if (p.id === selectedProductForDistribution.id) {
            const oldAvail = p.stock_details.quantidade_disponivel || 0;
            const oldReserved = p.stock_details.quantidade_reservada || 0;
            return {
              ...p,
              quantity_removed_today: result.new_daily_removed,
              stock_details: {
                ...p.stock_details,
                quantidade_disponivel: oldAvail - totalDistributed,
                quantidade_reservada: oldReserved + totalDistributed
              }
            };
          }
          return p;
        }));
        fetchData();
        fetchPlanning();
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

  // Saída AVULSA: o item sai do estoque agora e não volta.
  // Não passa por demanda, não gera reserva e não tem reconciliação depois —
  // é para perda, amostra, uso interno, venda fora do fluxo de demanda.
  const handleStandaloneRemoval = async () => {
    const product = selectedProductForDistribution;
    if (!product) return;

    setIsRemovingStandalone(true);
    try {
      const result = await ProductionService.registerStandaloneRemoval({
        product_id: product.id,
        quantity: product.totalToDistribute,
        date: selectedDate
      });

      if (result.success) {
        toast.success(result.message || 'Saída avulsa registrada.');
        setStandaloneRemovalOpen(false);
        setDistributionModalOpen(false);
        setInputs(prev => ({ ...prev, [product.id]: '' }));
        fetchData();
        fetchPlanning();
      } else {
        toast.error(result.error || 'Erro ao registrar saída avulsa.');
      }
    } catch (error) {
      const errorMessage = error.response?.data?.error || error.message || 'Erro ao registrar saída avulsa.';
      toast.error(errorMessage);
    } finally {
      setIsRemovingStandalone(false);
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
        fetchData();
        fetchPlanning();
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






  if (loading && products.length === 0) {
    return <div className="flex justify-center items-center h-screen"><Loader2 className="animate-spin h-8 w-8" /></div>;
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      <ProductionPlanningViews
        tipo={tipo}
        capaSubTab={capaSubTab}
        setCapaSubTab={setCapaSubTab}
        view={activeTab}
        setView={setActiveTab}
        planning={planning}
        loading={planningLoading}
        error={planningError}
        products={products}
        filter={filter}
        setFilter={setFilter}
        inputs={inputs}
        onInputChange={handleInputChange}
        onProduction={handleProduction}
        onRemoval={handleRemovalClick}
        onLog={handleLogClick}
        includeSimulations={includeSimulations}
        setIncludeSimulations={setIncludeSimulations}
        horizonte={horizonte}
        setHorizonte={(next) => setHorizonte(next.length ? next : ['atrasado', 'hoje', 'sem_prazo'])}
        onRefresh={() => { fetchData(); fetchPlanning(); if (activeTab === 'previsao') fetchPrevisao(); }}
        previsao={tipo === 'miolo' ? {
          data: previsao, loading: previsaoLoading, error: previsaoError,
          filtros: previsaoFiltros, onChangeFiltros: setPrevisaoFiltros, onRefresh: fetchPrevisao,
        } : null}
      />
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
              <p className="text-sm text-blue-900 font-medium">Para onde vão estas <strong>{selectedProductForDistribution?.totalToDistribute}</strong> unidades?</p>
              <p className="text-[10px] text-blue-700 mt-1">Em demandas reais, o item fica reservado até a finalização. Nas simulações, a atualização afeta somente o cenário. Também é possível registrar uma saída avulsa.</p>
            </div>

            {/* Saída avulsa como destino de primeira classe, no mesmo lugar em que
                o operador escolhe a demanda. É a alternativa natural quando o item
                está saindo sem ser para um pedido — não faz sentido escondê-la. */}
            <button
              type="button"
              onClick={() => setStandaloneRemovalOpen(true)}
              disabled={isDistributing}
              className="flex items-center justify-between gap-3 w-full text-left p-3 rounded-lg border border-destructive/30 bg-destructive/5 hover:bg-destructive/10 transition-colors disabled:opacity-50"
            >
              <div className="flex items-center gap-3">
                <PackageMinus className="h-5 w-5 text-destructive shrink-0" />
                <div>
                  <div className="font-bold text-sm text-destructive">Saída avulsa — sem demanda</div>
                  <div className="text-[10px] text-muted-foreground">Perda, amostra, uso interno. Baixa imediata e definitiva no estoque.</div>
                </div>
              </div>
              <Badge variant="outline" className="border-destructive/40 text-destructive shrink-0">Selecionar</Badge>
            </button>

            <ScrollArea type="always" className="h-[55vh] max-h-[55vh] min-h-0 flex-none border rounded-md">
              {distributionLoading ? (
                <div className="flex justify-center py-12"><Loader2 className="animate-spin h-8 w-8" /></div>
              ) : pendingDemandsForProduct.length === 0 ? (
                <div className="text-center py-12 px-6 text-muted-foreground">
                  <p>Nenhuma demanda ativa encontrada para este item com saldo pendente.</p>
                  <p className="text-xs mt-2">Use a saída avulsa acima se o item está saindo sem ser para um pedido.</p>
                </div>
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
                            <div className="font-bold text-sm text-gray-900 flex items-center gap-2">
                              {demanda.nome}
                              {demanda.simulacao && <Badge variant="outline" className="border-amber-400 text-amber-700">Simulação</Badge>}
                            </div>
                            <div className="text-[10px] text-muted-foreground uppercase">
                              {demanda.data_entrega ? format(new Date(demanda.data_entrega), 'dd/MM/yyyy') : 'Sem prazo'} - {demanda.canal_venda_nome || demanda.status || ''}
                            </div>
                          </TableCell>
                          <TableCell className="text-center py-3">
                            <Badge variant="outline">{(planning?.products || []).find(row => String(row.product_id) === String(selectedProductForDistribution.id))?.demandas
                              .filter(row => String(row.demanda_id) === String(demanda.id))
                              .reduce((sum, row) => sum + row.pendente, 0) || '—'} pendentes</Badge>
                          </TableCell>
                          <TableCell className="text-right py-3">
                            <Button 
                              size="sm" 
                              disabled={demanda.simulacao && demanda.status === 'RASCUNHO'}
                              onClick={async () => {
                                setSelectedDemandaId(demanda.id);
                                // 1. Buscar os itens detalhados desta demanda para validar
                                try {
                                  const apiBase = demanda.simulacao ? '/api/v2/demanda-simulacoes' : '/api/v2/demanda_producao';
                                  const res = await fetch(`${apiBase}/${demanda.id}`);
                                  const dData = await res.json();
                                  
                                  if (!dData.success || !dData.demanda?.itens) {
                                    toast.error("Erro ao validar itens da demanda.");
                                    return;
                                  }

                                  const itens = dData.demanda.itens;
                                  const relatedRows = (planning?.products || [])
                                    .find(row => String(row.product_id) === String(selectedProductForDistribution.id))?.demandas
                                    .filter(row => String(row.demanda_id) === String(demanda.id)) || [];
                                  const relatedItemIds = new Set(relatedRows.map(row => String(row.item_id)));
                                  const matchingItens = itens.filter(i => relatedItemIds.has(String(i.id))
                                    || String(i.id_produto_miolo || '') === String(selectedProductForDistribution.id)
                                    || String(i.produto_id || '') === String(selectedProductForDistribution.id)
                                    || (selectedProductForDistribution.sku && String(i.sku || '').trim().toLowerCase() === String(selectedProductForDistribution.sku).trim().toLowerCase()));

                                  if (matchingItens.length === 0) {
                                    toast.error('Não foi possível identificar um item correspondente nesta demanda.');
                                    return;
                                  }

                                  if (demanda.simulacao) {
                                    const field = tipo === 'miolo' ? 'miolos_prontos_retirada_qtd' : capaSubTab === 'impressas' ? 'capas_impressas_qtd' : 'capas_produzidas_qtd';
                                    let remaining = selectedProductForDistribution.totalToDistribute;
                                    const updates = [];
                                    matchingItens.forEach(item => {
                                      if (remaining <= 0) return;
                                      const needed = Math.max(0, Number(item.quantidade_total || item.quantidade || 0) - Number(item[field] || 0));
                                      const quantity = Math.min(remaining, needed);
                                      if (quantity > 0) {
                                        updates.push({ item_id: item.id, producao_incremental: { [field]: quantity } });
                                        remaining -= quantity;
                                      }
                                    });
                                    if (!updates.length) {
                                      toast.warning('Não há saldo pendente correspondente nesta simulação.');
                                      return;
                                    }
                                    if (remaining > 0) toast.warning(`A simulação aceita somente ${selectedProductForDistribution.totalToDistribute - remaining} unidades pendentes.`);
                                    const simResult = await fetch(`${apiBase}/${demanda.id}/acoes`, {
                                      method: 'POST',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({
                                        version: dData.demanda.version,
                                        operation_id: crypto.randomUUID(),
                                        action: 'producao',
                                        payload: { updates },
                                      }),
                                    }).then(response => response.json());
                                    if (!simResult.success) throw new Error(simResult.message || 'Falha ao atualizar a simulação.');
                                    toast.success('Produção registrada somente na simulação.');
                                    setDistributionModalOpen(false);
                                    fetchPlanning();
                                    return;
                                  }

                                  // 2. Realizar distribuição automática Top-Down
                                  let remaining = selectedProductForDistribution.totalToDistribute;
                                  const dists = {};
                                  
                                  matchingItens.forEach(item => {
                                    if (remaining <= 0) return;
                                    const field = tipo === 'miolo' ? 'miolos_prontos_retirada_qtd' : capaSubTab === 'impressas' ? 'capas_impressas_qtd' : 'capas_produzidas_qtd';
                                    const current = parseFloat(item[field] || 0);
                                    const factor = relatedRows.find(row => String(row.item_id) === String(item.id))?.fator || 1;
                                    const needed = Math.max(0, (parseFloat(item.quantidade_total) - current) * factor);
                                    
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

                                  if (remaining > 0) {
                                    toast.warning(`Somente ${selectedProductForDistribution.totalToDistribute - remaining} unidades têm saldo pendente nesta demanda.`);
                                  }

                                  setDistributionQuantities(dists);
                                  handleDistributionSubmit(dists, demanda.id);
                                } catch (err) {
                                  const errorMessage = err.message || 'Erro ao processar demanda.';
                                  toast.error(errorMessage);
                                }
                              }}
                            >
                              {demanda.simulacao && demanda.status === 'RASCUNHO' ? 'Não publicada' : 'Selecionar'}
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
              onClick={() => handleDistributionSubmit()}
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
      {/* Confirmação da saída avulsa. Diferente da alocação, isto não tem volta
          pelo fluxo normal: o estoque é baixado na hora, sem reserva e sem
          reconciliação posterior. */}
      <AlertDialog open={standaloneRemovalOpen} onOpenChange={setStandaloneRemovalOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Registrar saída avulsa?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  <strong>{selectedProductForDistribution?.totalToDistribute}</strong> un de{' '}
                  <strong>{selectedProductForDistribution?.name}</strong> ({selectedProductForDistribution?.sku})
                  sairão do estoque imediatamente.
                </p>
                <p className="text-xs">
                  A saída não fica vinculada a nenhuma demanda e não passa por reconciliação.
                  Use para perda, amostra, uso interno ou venda fora do fluxo de demandas.
                </p>
                <p className="text-xs">
                  Só o saldo <strong>disponível</strong> pode sair — o que está reservado para
                  demandas permanece intocado.
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRemovingStandalone}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); handleStandaloneRemoval(); }}
              disabled={isRemovingStandalone}
            >
              {isRemovingStandalone && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Confirmar saída
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
