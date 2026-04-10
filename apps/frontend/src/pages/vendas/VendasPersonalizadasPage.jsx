import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import OrderCard from '@/components/vendas/OrderCard';
import OrderFilters from '@/components/vendas/OrderFilters';
import { ArrowLeft, Badge, Brain, Loader2, ThumbsDown, Database, ChevronDown, Settings } from 'lucide-react';
import { useEffect, useRef, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { personalizadosService } from '@/services/personalizadosService';

const ITEMS_PER_PAGE = 20;

function VendasPersonalizadasPage() {
  const navigate = useNavigate();
  const highlightedMessageRef = useRef(null);
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  
  // Pagination/Slicing
  const [visibleCount, setVisibleCount] = useState(ITEMS_PER_PAGE);

  // Chat State
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [selectedChatUser, setSelectedChatUser] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [loadingChat, setLoadingChat] = useState(false);
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

  useEffect(() => {
    fetchMode();
  }, []);

  // Só carrega pedidos DEPOIS de saber o modo correto
  useEffect(() => {
    if (opMode !== null) {
      fetchOrders();
    }
  }, [opMode]);

  // Debounce search term
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
  const filteredOrders = useMemo(() => {
    let result = orders;

    // Apply search filter
    if (debouncedSearchTerm) {
      const term = debouncedSearchTerm.toLowerCase();
      result = result.filter(order =>
        order.numero.toString().includes(term) ||
        order.numeroLoja?.toString().includes(term) ||
        (order.contato?.nome || '').toLowerCase().includes(term) ||
        (order.shopee?.username || '').toLowerCase().includes(term)
      );
    }

    // Apply status filter
    if (statusFilter) {
      result = result.filter(order => {
        if (statusFilter === 'with_chat') {
          return order.has_chat_messages === true;
        } else if (statusFilter === 'without_chat') {
          return order.has_chat_messages !== true;
        }

        if (order.itens && order.itens.length > 0) {
          for (const item of order.itens) {
            if (item.personalizations && item.personalizations.length > 0) {
              if (statusFilter === 'success') {
                return item.personalizations.some(p => p.status === 'SUCCESS');
              } else if (statusFilter === 'needs_review') {
                return item.personalizations.some(p => p.status === 'NEEDS_REVIEW');
              } else if (statusFilter === 'no_personalization') {
                return item.personalizations.every(p => p.status === 'NO_PERSONALIZATION_FOUND' || !p.status);
              }
            }
          }
        }

        if (statusFilter === 'no_personalization') {
          const hasAnyPersonalizations = order.itens && order.itens.some(item =>
            item.personalizations && item.personalizations.length > 0
          );
          return !hasAnyPersonalizations;
        }

        return false;
      });
    }

    return result;
  }, [orders, debouncedSearchTerm, statusFilter]);

  // Memoized status counts
  const statusCounts = useMemo(() => {
    const counts = {
      all: orders.length,
      success: 0,
      needs_review: 0,
      no_personalization: 0
    };

    orders.forEach(order => {
      let hasSuccess = false;
      let hasNeedsReview = false;
      let hasNoPersonalization = true;
      let hasAnyPersonalizations = false;

      if (order.itens && order.itens.length > 0) {
        for (const item of order.itens) {
          if (item.personalizations && item.personalizations.length > 0) {
            hasAnyPersonalizations = true;
            if (item.personalizations.some(p => p.status === 'SUCCESS')) {
              hasSuccess = true;
            }
            if (item.personalizations.some(p => p.status === 'NEEDS_REVIEW')) {
              hasNeedsReview = true;
            }
            if (!item.personalizations.every(p => p.status === 'NO_PERSONALIZATION_FOUND' || !p.status)) {
              hasNoPersonalization = false;
            }
          }
        }
      }

      if (hasSuccess) counts.success++;
      if (hasNeedsReview) counts.needs_review++;
      if (hasNoPersonalization && hasAnyPersonalizations) counts.no_personalization++;
    });

    return counts;
  }, [orders]);

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
      const data = await personalizadosService.processar({ shopee_order_sn: orderSn });
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

  const handleOpenChat = async (username, orderId, orderData) => {
    if (!username) {
        toast.error("Usuário não identificado para este pedido.");
        return;
    }
    setSelectedChatUser({ username, orderId });
    setIsChatOpen(true);
    setLoadingChat(true);
    setChatMessages([]);

    // Set highlighted messages
    const personalizationMessageIds = [];
    if (orderData.itens) {
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

    try {
      const data = await personalizadosService.getChat(username);
      if (data.success) {
        setChatMessages(Array.isArray(data.data?.messages) ? data.data.messages : []);
      } else {
        throw new Error(data.message || 'Falha ao carregar mensagens');
      }
    } catch (e) {
      toast.error(e.message);
    } finally {
      setLoadingChat(false);
    }
  };

  // Scroll to highlighted message when chat opens or messages load
  useEffect(() => {
    if (!loadingChat && chatMessages.length > 0 && highlightedMessageRef.current) {
      setTimeout(() => {
        highlightedMessageRef.current.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'center' 
        });
      }, 300);
    }
  }, [loadingChat, chatMessages]);

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
          <Brain className="mr-2 h-4 w-4" /> Identificar Nomes IA
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

      {/* Chat Sheet */}
      <Sheet open={isChatOpen} onOpenChange={setIsChatOpen}>
        <SheetContent className="w-[400px] sm:w-[540px] flex flex-col h-full" side="right">
          <SheetHeader className="border-b pb-4">
            <SheetTitle>Chat do Pedido #{selectedChatUser?.orderId}</SheetTitle>
            <SheetDescription>
              Conversa com @{selectedChatUser?.username}
            </SheetDescription>
          </SheetHeader>
          
          <ScrollArea className="flex-1 pr-4 mt-4">
            {loadingChat ? (
                <div className="flex justify-center p-8"><Loader2 className="h-8 w-8 animate-spin" /></div>
            ) : chatMessages.length === 0 ? (
                <div className="text-center text-muted-foreground py-8">Nenhuma mensagem encontrada.</div>
            ) : (
                <div className="space-y-4 pb-4">
                    {chatMessages.map((msg) => {
                        const isCustomer = msg.from_user_name === selectedChatUser?.username;
                        const isHighlighted = highlightedMessages.some(hId => String(hId) === String(msg.id));

                        return (
                            <div 
                                key={msg.id} 
                                ref={isHighlighted ? highlightedMessageRef : null}
                                className={`flex ${isCustomer ? 'justify-start' : 'justify-end'}`}
                            >
                                <div className={`max-w-[80%] rounded-lg p-3 shadow-sm ${
                                    isHighlighted 
                                        ? 'bg-yellow-50 border-2 border-yellow-400 ring-2 ring-yellow-400 ring-opacity-20' 
                                        : isCustomer ? 'bg-gray-100 border border-gray-200' : 'bg-blue-600 text-white'
                                }`}>
                                    <div className={`text-sm ${isHighlighted ? 'text-gray-900 font-medium' : ''}`}>
                                        {msg.display_content}
                                    </div>
                                    <div className={`text-[10px] mt-1 text-right ${
                                        isHighlighted ? 'text-yellow-700' : isCustomer ? 'text-gray-500' : 'text-blue-100'
                                    }`}>
                                        {new Date(msg.created_at).toLocaleString()}
                                    </div>
                                    {isHighlighted && (
                                        <div className="text-[10px] mt-1 text-yellow-700 font-bold border-t border-yellow-200 pt-1 flex items-center gap-1">
                                            <Brain className="h-3 w-3" /> Fonte de identificação IA
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
          </ScrollArea>
        </SheetContent>
      </Sheet>

      {/* AI Logs Modal */}
      <Dialog open={isLogsModalOpen} onOpenChange={setIsLogsModalOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Logs de Execução da IA - Pedido: {selectedOrderForLogs}</DialogTitle>
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
                    <CardContent className="space-y-4">
                      <div>
                        <h6 className="font-semibold mb-2">Input</h6>
                        <pre className="bg-gray-100 p-3 rounded text-xs overflow-x-auto">
                          <code>{JSON.stringify(JSON.parse(log.input_data), null, 2)}</code>
                        </pre>
                      </div>
                      <div>
                        <h6 className="font-semibold mb-2">Chat Context</h6>
                        <pre className="bg-gray-100 p-3 rounded text-xs overflow-x-auto">
                          <code>{JSON.stringify(JSON.parse(log.chat_context), null, 2)}</code>
                        </pre>
                      </div>
                      <div>
                        <h6 className="font-semibold mb-2">Extracted Personalization</h6>
                        <pre className="bg-gray-100 p-3 rounded text-xs overflow-x-auto">
                          <code>{JSON.stringify(JSON.parse(log.extracted_personalization), null, 2)}</code>
                        </pre>
                      </div>
                      <div>
                        <h6 className="font-semibold mb-2">Model Result</h6>
                        <pre className="bg-gray-100 p-3 rounded text-xs overflow-x-auto">
                          <code>{JSON.stringify(JSON.parse(log.model_result), null, 2)}</code>
                        </pre>
                      </div>
                      {log.error_message && (
                        <div>
                          <h6 className="font-semibold mb-2 text-red-600">Error</h6>
                          <pre className="bg-red-50 p-3 rounded text-xs overflow-x-auto border border-red-200">
                            <code>{log.error_message}</code>
                          </pre>
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
