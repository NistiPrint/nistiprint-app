import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ChatSidebar } from '@/components/chat/ChatSidebar';
import OrderCard from '@/components/vendas/OrderCard';
import OrderFilters from '@/components/vendas/OrderFilters';
import { ArrowLeft, Brain, Loader2, ThumbsDown, Database, ChevronDown, ChevronRight, Settings, Terminal, FileText, RefreshCw, Search, AlertTriangle, CheckCircle, XCircle, Clock, ListChecks, MessageSquare } from 'lucide-react';
import { useEffect, useState, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { personalizadosService } from '@/services/personalizadosService';

const ITEMS_PER_PAGE = 20;

function VendasPersonalizadasPage() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Tab navigation (4 abas consolidadas)
  const [activeTab, setActiveTab] = useState('pendentes'); // pendentes | identificados | historico | logs

  // AI Logs (for Logs tab)
  const [globalAiLogs, setGlobalAiLogs] = useState([]);
  const [loadingGlobalLogs, setLoadingGlobalLogs] = useState(false);
  
  // Pagination/Slicing
  const [visibleCount, setVisibleCount] = useState(ITEMS_PER_PAGE);

  // Chat State
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [selectedChatUser, setSelectedChatUser] = useState(null);
  const [highlightedMessages, setHighlightedMessages] = useState([]);

  // AI Logs Modal
  const [isLogsModalOpen, setIsLogsModalOpen] = useState(false);
  const [selectedOrderForLogs, setSelectedOrderForLogs] = useState(null);
  const [aiLogs, setAiLogs] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  // Feedback Modal
  const [isFeedbackModalOpen, setIsFeedbackModalOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState(null);
  const [feedbackNotes, setFeedbackNotes] = useState('');
  const [selectedOrderForFeedback, setSelectedOrderForFeedback] = useState(null);
  
  // Operational Mode State
  const [opMode, setOpMode] = useState(null); // null = ainda não carregou
  const [updatingMode, setUpdatingMode] = useState(false);

  // Polling ref for batch processing
  const lotePollRef = useRef(null);

  useEffect(() => {
    fetchMode();
    // Cleanup polling on unmount
    return () => {
      if (lotePollRef.current) clearInterval(lotePollRef.current);
    };
  }, []);

  // Só carrega pedidos DEPOIS de saber o modo correto
  useEffect(() => {
    if (opMode !== null) {
      fetchOrders();
    }
  }, [opMode]);

  // Helper seguro para renderizar campos JSONB do banco
  // Supabase retorna objetos já parseados, mas às vezes vem como string
  const safeJsonDisplay = (value) => {
    if (value == null) return '(nulo)';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    if (typeof value === 'string') {
      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch {
        return value; // Retorna raw se não for JSON válido
      }
    }
    return String(value);
  };
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchTerm(searchTerm);
      setVisibleCount(ITEMS_PER_PAGE); // Reset pagination on search change
    }, 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  const fetchMode = async () => {
    try {
        const response = await fetch('/api/v2/configuracoes/sistema');
        const data = await response.json();
        if (data.success) setOpMode(data.database_operational_mode);
    } catch (e) { console.error(e); }
  };

  const toggleOpMode = async () => {
    const newMode = opMode === 'v2' ? 'legacy' : 'v2';
    setUpdatingMode(true);
    try {
        const response = await fetch('/api/v2/configuracoes/sistema', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ database_operational_mode: newMode })
        });
        const data = await response.json();
        if (data.success) {
            setOpMode(newMode);
            toast.success(`Modo de operação alterado para: ${newMode.toUpperCase()}`);
            // fetchOrders será chamado automaticamente pelo useEffect em opMode
        } else {
            toast.error("Erro ao alterar modo.");
        }
    } catch (e) {
        toast.error("Erro de conexão.");
    } finally {
        setUpdatingMode(false);
    }
  };

  const fetchOrders = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/v2/vendas/personalizadas?mode=${opMode}`, {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      setOrders(data.data?.bling_orders || []);
    } catch (e) {
      setError(e.message);
      toast.error(`Erro ao carregar vendas: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Memoized filtered orders
  // Aba + busca textual + statusFilter (IA + chat) — tudo combinado
  const filteredOrders = useMemo(() => {
    let result = orders;

    // 1. Filtro por aba (o principal)
    if (activeTab === 'pendentes') {
      result = result.filter(order => {
        if (!order.itens || order.itens.length === 0) return false;
        return order.itens.some(item =>
          item.personalizations &&
          item.personalizations.length > 0 &&
          item.personalizations.some(p =>
            p.status === 'NEEDS_REVIEW' ||
            !p.nome ||
            p.nome === null ||
            p.nome === ''
          )
        );
      });
    } else if (activeTab === 'identificados') {
      result = result.filter(order => {
        if (!order.itens || order.itens.length === 0) return false;
        return order.itens.some(item =>
          item.personalizations &&
          item.personalizations.length > 0 &&
          item.personalizations.some(p => p.status === 'SUCCESS' && p.nome)
        );
      });
    }
    // 'historico' = todos, 'logs' = não filtra orders

    // 2. Busca textual
    if (debouncedSearchTerm) {
      const term = debouncedSearchTerm.toLowerCase();
      result = result.filter(order =>
        order.numero.toString().includes(term) ||
        order.numeroLoja?.toString().includes(term) ||
        (order.contato?.nome || '').toLowerCase().includes(term) ||
        (order.shopee?.username || '').toLowerCase().includes(term)
      );
    }

    // 3. Filtro por status IA (funciona como refinamento da aba)
    if (statusFilter === 'success') {
      result = result.filter(order =>
        order.itens?.some(item =>
          item.personalizations?.some(p => p.status === 'SUCCESS')
        )
      );
    } else if (statusFilter === 'needs_review') {
      result = result.filter(order =>
        order.itens?.some(item =>
          item.personalizations?.some(p => p.status === 'NEEDS_REVIEW')
        )
      );
    } else if (statusFilter === 'no_personalization') {
      result = result.filter(order => {
        const hasAnyPersonalizations = order.itens?.some(item =>
          item.personalizations && item.personalizations.length > 0
        );
        return !hasAnyPersonalizations;
      });
    } else if (statusFilter === 'with_chat') {
      result = result.filter(order => order.has_chat_messages === true);
    } else if (statusFilter === 'without_chat') {
      result = result.filter(order => order.has_chat_messages !== true);
    }

    return result;
  }, [orders, activeTab, debouncedSearchTerm, statusFilter]);

  // Memoized status counts (contadores REAIS para filtros e abas)
  const statusCounts = useMemo(() => {
    const counts = {
      all: orders.length,
      pendentes: 0,
      identificados: 0,
      historico: orders.length,
      // IA status counts (para os botões de filtro)
      success: 0,
      needs_review: 0,
      no_personalization: 0,
      // Chat counts
      with_chat: 0,
      without_chat: 0,
    };

    orders.forEach(order => {
      let hasPending = false;
      let hasIdentified = false;
      let hasSuccess = false;
      let hasNeedsReview = false;
      let hasNoPersonalization = true;
      let hasAnyPersonalizations = false;

      if (order.itens && order.itens.length > 0) {
        for (const item of order.itens) {
          if (item.personalizations && item.personalizations.length > 0) {
            hasAnyPersonalizations = true;
            hasNoPersonalization = false;

            if (item.personalizations.some(p => p.status === 'SUCCESS')) {
              hasSuccess = true;
              if (item.personalizations.some(p => p.nome)) hasIdentified = true;
            }
            if (item.personalizations.some(p => p.status === 'NEEDS_REVIEW')) {
              hasNeedsReview = true;
              hasPending = true;
            }
            if (item.personalizations.some(p => !p.nome || p.nome === null || p.nome === '')) {
              hasPending = true;
            }
          }
        }
      }

      if (hasPending) counts.pendentes++;
      if (hasIdentified) counts.identificados++;
      if (hasSuccess) counts.success++;
      if (hasNeedsReview) counts.needs_review++;
      if (hasNoPersonalization && hasAnyPersonalizations) counts.no_personalization++;
      if (order.has_chat_messages === true) counts.with_chat++;
      else counts.without_chat++;
    });

    return counts;
  }, [orders]);

  // Load global AI logs for the Logs tab
  const loadGlobalLogs = async () => {
    setLoadingGlobalLogs(true);
    try {
      const data = await personalizadosService.getAllLogs({ limit: 100 });
      if (data.success && data.data?.logs) {
        setGlobalAiLogs(data.data.logs);
      }
    } catch (e) {
      console.error('Erro ao carregar logs globais:', e);
    } finally {
      setLoadingGlobalLogs(false);
    }
  };

  // Load global logs when switching to logs tab
  const logsLoadedRef = useRef(false);
  useEffect(() => {
    if (activeTab === 'logs' && !logsLoadedRef.current) {
      logsLoadedRef.current = true;
      loadGlobalLogs();
    }
  }, [activeTab]);

  // Sliced orders for display
  const slicedOrders = useMemo(() => {
    return filteredOrders.slice(0, visibleCount);
  }, [filteredOrders, visibleCount]);

  const loadMore = () => {
    setVisibleCount(prev => prev + ITEMS_PER_PAGE);
  };

  const handleProcessAI = async (orderSn) => {
    if (!orderSn) {
      toast.error('Não é possível processar: Número do pedido Shopee não encontrado.');
      return;
    }
    const toastId = toast.loading('Processando com IA...');
    try {
      // Backend espera 'order_sn', não 'shopee_order_sn'
      const data = await personalizadosService.processar({ order_sn: orderSn, limit: 1 });
      if (data.success) {
        toast.success(data.message || 'Pedido processado com sucesso!', { id: toastId });
        fetchOrders();
      } else {
        toast.error(data.message || 'Erro ao processar pedido', { id: toastId });
      }
    } catch (e) {
      toast.error('Erro de rede ao processar pedido', { id: toastId });
    }
  };

  const [isProcessingLote, setIsProcessingLote] = useState(false);

  const handleProcessarLote = async () => {
    const confirm = window.confirm(`Processar TODOS os pedidos personalizados com IA? Isso pode demorar alguns minutos.`);
    if (!confirm) return;

    setIsProcessingLote(true);
    const toastId = toast.loading('Processando lote com IA...');
    const lastLogCount = aiLogs.length; // Track if new logs appeared

    try {
      // limit: 0 = todos os pedidos
      const data = await personalizadosService.processar({ limit: 0 });
      if (!data.success) {
        toast.error(data.message || 'Erro ao processar lote', { id: toastId });
        setIsProcessingLote(false);
        return;
      }

      toast.success(data.message || 'Processamento iniciado!', { id: toastId });

      // Start polling: check for new logs every 5s, refresh orders when done
      let pollCount = 0;
      const maxPolls = 120; // 10 minutes at 5s intervals

      if (lotePollRef.current) clearInterval(lotePollRef.current);

      lotePollRef.current = setInterval(() => {
        pollCount++;

        // Check if new logs appeared
        personalizadosService.getAllLogs({ limit: 1 })
          .then(logData => {
            if (logData.success && logData.data.logs && logData.data.logs.length > 0) {
              const latest = logData.data.logs[0];
              const age = Date.now() - new Date(latest.executed_at).getTime();
              // If latest log is > 15s old, processing likely finished
              if (age > 15000) {
                if (lotePollRef.current) clearInterval(lotePollRef.current);
                setIsProcessingLote(false);
                fetchOrders();
                toast.success('Processamento de lote concluído!');
              }
            } else if (pollCount > 6) {
              // After 30s with no logs at all, assume done
              if (lotePollRef.current) clearInterval(lotePollRef.current);
              setIsProcessingLote(false);
              fetchOrders();
            }
          })
          .catch(() => {});

        // Timeout after 10 minutes
        if (pollCount >= maxPolls) {
          if (lotePollRef.current) clearInterval(lotePollRef.current);
          setIsProcessingLote(false);
          fetchOrders();
          toast.warning('Processamento pode ainda estar em andamento. Verifique os logs.');
        }
      }, 5000);

    } catch (e) {
      toast.error('Erro de rede ao processar lote', { id: toastId });
      setIsProcessingLote(false);
    }
  };

  const handleOpenChat = async (username, orderId, orderData) => {
    if (!username) {
        toast.error("Usuário não identificado para este pedido.");
        return;
    }

    // Extrair IDs das mensagens que originaram personalizações
    const personalizationMessageIds = [];
    if (orderData?.itens) {
      orderData.itens.forEach(item => {
        if (item.personalizations) {
          item.personalizations.forEach(p => {
            if (p.name_source_message_id) personalizationMessageIds.push(p.name_source_message_id);
            if (p.initial_source_message_id) personalizationMessageIds.push(p.initial_source_message_id);
          });
        }
      });
    }
    setHighlightedMessages(personalizationMessageIds);
    setSelectedChatUser({ username, orderId });
    setIsChatOpen(true);
  };

  const handleOpenAiLogs = async (orderSn) => {
    setSelectedOrderForLogs(orderSn);
    setIsLogsModalOpen(true);
    setLoadingLogs(true);
    setAiLogs([]);

    try {
      const data = await personalizadosService.getLogs(orderSn);
      if (data.success) {
        setAiLogs(Array.isArray(data.data?.logs) ? data.data.logs : []);
      } else {
        throw new Error(data.message || 'Falha ao carregar logs');
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoadingLogs(false);
    }
  };

  const handleFeedback = (orderId, feedbackType) => {
    setSelectedOrderForFeedback(orderId);
    setFeedbackType(feedbackType);
    setFeedbackNotes('');
    if (feedbackType === 0) { // Negative feedback requires notes
      setIsFeedbackModalOpen(true);
    } else {
      submitFeedback(orderId, feedbackType);
    }
  };

  const submitFeedback = async (orderId, feedbackType, notes = '') => {
    const toastId = toast.loading('Enviando feedback...');
    try {
      const data = await personalizadosService.salvarFeedback({
        order_sn: orderId,
        avaliacao: feedbackType === 1 ? 5 : 1,
        texto_feedback: notes
      });
      if (data.success) {
        toast.success(feedbackType === 1 ? 'Obrigado pelo feedback positivo!' : 'Obrigado pelo feedback. Vamos analisar o ocorrido.', { id: toastId });
        setIsFeedbackModalOpen(false);
      } else {
        toast.error(data.message || 'Erro ao enviar feedback', { id: toastId });
      }
    } catch (e) {
      toast.error('Erro ao enviar feedback', { id: toastId });
    }
  };

  if (loading) return <div className="flex justify-center p-8"><Loader2 className="h-8 w-8 animate-spin" /></div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  // Componente colapsável para seções de log
  const CollapsibleSection = ({ icon: Icon, title, content, defaultOpen = false }) => {
    const [open, setOpen] = useState(defaultOpen);

    if (!content) return null;

    return (
      <div className="border rounded overflow-hidden">
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium"
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <Icon className="h-4 w-4 text-muted-foreground" />
          {title}
        </button>
        {open && (
          <pre className="text-xs bg-white p-3 overflow-x-auto max-h-96 whitespace-pre-wrap border-t">
            {safeJsonDisplay(content)}
          </pre>
        )}
      </div>
    );
  };

  return (
    <div className="container mx-auto py-8 px-2">
      <h1 className="text-3xl font-bold mb-6 text-center flex items-center justify-center gap-4">
        <Button variant="outline" onClick={() => navigate('/')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Voltar
        </Button>
        <Button variant="outline" onClick={() => navigate('/configuracoes/ia')}>
          <Settings className="mr-2 h-4 w-4" /> Config IA
        </Button>
        <Button variant="outline" onClick={() => navigate('/ferramentas')}>
          <Brain className="mr-2 h-4 w-4" /> Ferramentas IA
        </Button>
        <Button variant="outline" onClick={handleProcessarLote} disabled={isProcessingLote}>
          {isProcessingLote ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Brain className="mr-2 h-4 w-4" />}
          {isProcessingLote ? 'Processando...' : 'Processar Lote IA'}
        </Button>
        <Button
          variant={opMode === 'legacy' ? 'destructive' : 'outline'}
          onClick={toggleOpMode}
          disabled={updatingMode || opMode === null}
          className="gap-2"
          title={`Fonte atual: ${opMode === 'legacy' ? 'MySQL (Legado)' : opMode === 'v2' ? 'Supabase (V2)' : 'Carregando...'} — Clique para alternar`}
        >
          <Database className={`h-4 w-4 ${updatingMode ? 'animate-pulse' : ''}`} />
          {opMode === null ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <>Fonte: {opMode.toUpperCase()}</>
          )}
        </Button>
        Pedidos Personalizados
      </h1>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => { setActiveTab(v); setVisibleCount(ITEMS_PER_PAGE); }} className="mb-6">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="pendentes" className="flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Pendentes Extração
            <Badge variant={statusCounts.pendentes > 0 ? "default" : "secondary"} className="ml-1 h-5 min-w-5 flex items-center justify-center text-xs">
              {statusCounts.pendentes}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="identificados" className="flex items-center gap-2">
            <CheckCircle className="h-4 w-4" />
            Nomes Extraídos
            <Badge variant={statusCounts.identificados > 0 ? "default" : "secondary"} className="ml-1 h-5 min-w-5 flex items-center justify-center text-xs">
              {statusCounts.identificados}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="historico" className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            Histórico
            <Badge variant="outline" className="ml-1 h-5 min-w-5 flex items-center justify-center text-xs">
              {statusCounts.historico}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="logs" className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4" />
            Logs IA
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Tab Content: Orders (pendentes, identificados, historico) */}
      {activeTab !== 'logs' && (
      <Card className="shadow-sm border-light">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Filtrar pedidos
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {/* Filters */}
          <OrderFilters
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
            statusFilter={statusFilter}
            onStatusFilterChange={(val) => {
                setStatusFilter(val);
                setVisibleCount(ITEMS_PER_PAGE);
            }}
            statusCounts={statusCounts}
          />

          {/* Orders */}
          {slicedOrders.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground bg-white">
              <div className="max-w-md mx-auto">
                {orders.length === 0 ? (
                  <div>
                    <div className="text-6xl mb-4">📦</div>
                    <h3 className="text-lg font-medium mb-2">Nenhum pedido encontrado</h3>
                    <p className="text-sm">Não há pedidos personalizados disponíveis no momento.</p>
                  </div>
                ) : (
                  <div>
                    <div className="text-6xl mb-4">🔍</div>
                    <h3 className="text-lg font-medium mb-2">Nenhum resultado</h3>
                    <p className="text-sm">Tente ajustar os filtros de busca para encontrar pedidos.</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-white p-6 space-y-4">
              {slicedOrders.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onOpenChat={handleOpenChat}
                  onOpenAiLogs={handleOpenAiLogs}
                  onProcessAI={handleProcessAI}
                  onFeedback={handleFeedback}
                />
              ))}
              
              {filteredOrders.length > visibleCount && (
                <div className="flex justify-center pt-6">
                  <Button variant="outline" onClick={loadMore} className="gap-2">
                    <ChevronDown className="h-4 w-4" />
                    Carregar mais ({filteredOrders.length - visibleCount} restantes)
                  </Button>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {/* Tab Content: Logs IA */}
      {activeTab === 'logs' && (
      <Card className="shadow-sm border-light">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center justify-between">
            <span className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4" />
              Logs de Execução da IA
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={loadGlobalLogs}
              disabled={loadingGlobalLogs}
            >
              {loadingGlobalLogs ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw className="h-3 w-3 mr-1" />}
              Atualizar
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loadingGlobalLogs ? (
            <div className="flex justify-center p-8">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : globalAiLogs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Nenhum log de execução encontrado.
            </div>
          ) : (
            <div className="space-y-4">
              {globalAiLogs.map((log, index) => (
                <Card key={log.id} className="border">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center justify-between">
                      <span className="font-mono text-xs">
                        {log.order_sn || 'N/A'}
                      </span>
                      <Badge variant={log.status === 'success' ? 'default' : 'destructive'} className="text-xs">
                        {log.status}
                      </Badge>
                    </CardTitle>
                    <div className="text-xs text-muted-foreground">
                      {log.executed_at ? new Date(log.executed_at).toLocaleString('pt-BR') : '-'}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <CollapsibleSection
                      icon={Terminal}
                      title="Prompt enviado"
                      content={log.input_data}
                      defaultOpen={false}
                    />
                    <CollapsibleSection
                      icon={Brain}
                      title="Resposta IA"
                      content={log.model_result}
                      defaultOpen={false}
                    />
                    <CollapsibleSection
                      icon={FileText}
                      title="Personalizações"
                      content={log.extracted_personalization}
                      defaultOpen={false}
                    />
                    {log.error_message && (
                      <div className="bg-red-50 border border-red-200 rounded p-3">
                        <p className="text-xs font-medium text-red-800">Erro: {log.error_message}</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {/* Chat Sidebar */}
      <ChatSidebar
        open={isChatOpen}
        onOpenChange={setIsChatOpen}
        username={selectedChatUser?.username}
        orderId={selectedChatUser?.orderId}
        highlightedMessageIds={highlightedMessages}
      />

      {/* AI Logs Modal */}
      <Dialog open={isLogsModalOpen} onOpenChange={setIsLogsModalOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <span>Logs de Execução da IA - Pedido: {selectedOrderForLogs}</span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setLoadingLogs(true);
                    personalizadosService.getLogs(selectedOrderForLogs).then(data => {
                      setAiLogs(data.logs || []);
                      setLoadingLogs(false);
                    }).catch(() => setLoadingLogs(false));
                  }}
                  disabled={loadingLogs}
                >
                  {loadingLogs ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw className="h-3 w-3 mr-1" />}
                  Atualizar
                </Button>
                {aiLogs.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    onClick={async () => {
                      if (!window.confirm('Deletar todos os logs deste pedido?')) return;
                      const res = await personalizadosService.deleteLogs(selectedOrderForLogs);
                      toast.success(res.message || 'Logs deletados');
                      setAiLogs([]);
                    }}
                  >
                    Deletar Logs
                  </Button>
                )}
              </div>
            </DialogTitle>
          </DialogHeader>
          <div className="mt-4">
            {loadingLogs ? (
              <div className="flex justify-center p-8">
                <Loader2 className="h-8 w-8 animate-spin" />
              </div>
            ) : aiLogs.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                Nenhum log de execução encontrado para este pedido.
              </div>
            ) : (
              <div className="space-y-4">
                {aiLogs.map((log, index) => (
                  <Card key={log.id} className="border">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-lg flex items-center justify-between">
                        <span>Execução #{log.id}</span>
                        <Badge variant={log.status === 'success' ? 'default' : 'destructive'}>
                          {log.status}
                        </Badge>
                      </CardTitle>
                      <div className="text-sm text-muted-foreground">
                        Executado em: {new Date(log.executed_at).toLocaleString('pt-BR')}
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {/* Prompt Payload (Input Data) */}
                      <CollapsibleSection
                        icon={Terminal}
                        title={`Prompt enviado à IA (${typeof log.input_data === 'string' ? log.input_data.length + ' chars' : 'ver detalhes'})`}
                        content={log.input_data}
                        defaultOpen={false}
                      />

                      {/* Resposta da IA */}
                      <CollapsibleSection
                        icon={Brain}
                        title="Resposta da IA (JSON)"
                        content={log.model_result}
                        defaultOpen={false}
                      />

                      {/* Personalizações extraídas */}
                      <CollapsibleSection
                        icon={FileText}
                        title="Personalizações extraídas"
                        content={log.extracted_personalization}
                        defaultOpen={false}
                      />

                      {log.metadata && (
                        <CollapsibleSection
                          icon={Settings}
                          title="Metadata"
                          content={log.metadata}
                          defaultOpen={false}
                        />
                      )}

                      {/* Erro - sempre visível se existir */}
                      {log.error_message && (
                        <div className="bg-red-50 border border-red-200 rounded p-3">
                          <p className="text-sm font-medium text-red-800 mb-1">Erro:</p>
                          <pre className="text-xs text-red-700 whitespace-pre-wrap">{log.error_message}</pre>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Feedback Modal */}
      <Dialog open={isFeedbackModalOpen} onOpenChange={setIsFeedbackModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ThumbsDown className="h-5 w-5 text-red-500" />
              Reportar um Problema
            </DialogTitle>
          </DialogHeader>
          <div className="mt-4">
            <label className="block text-sm font-medium mb-2">
              Descreva o problema encontrado neste pedido:
            </label>
            <Textarea
              value={feedbackNotes}
              onChange={(e) => setFeedbackNotes(e.target.value)}
              placeholder="Explique o que está errado, para que possamos melhorar..."
              rows={4}
              className="w-full"
            />
            {!feedbackNotes.trim() && (
              <div className="text-sm text-red-500 mt-1">
                Por favor, descreva o problema.
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <Button
              variant="outline"
              onClick={() => setIsFeedbackModalOpen(false)}
            >
              Cancelar
            </Button>
            <Button
              variant="destructive"
              onClick={() => submitFeedback(selectedOrderForFeedback, feedbackType, feedbackNotes)}
              disabled={!feedbackNotes.trim()}
            >
              Enviar Feedback
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default VendasPersonalizadasPage;
