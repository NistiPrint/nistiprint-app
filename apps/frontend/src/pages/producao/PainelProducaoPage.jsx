import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuth } from '@/contexts/AuthContext';
import ProductionService from '@/services/ProductionService';
import { AlertTriangle, BarChart3, Clock, Package, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '@/lib/supabase';
import { toast } from 'sonner';

const PainelProducaoPage = () => {
  const { user } = useAuth();
  const [painelData, setPainelData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState(null);
  const [progressDialogOpen, setProgressDialogOpen] = useState(false);
  const [progressInputs, setProgressInputs] = useState({});
  const [updatingProgress, setUpdatingProgress] = useState(false);

  const fetchPainelData = async () => {
    // Only set loading on initial load to avoid flashing during updates
    if (!painelData) setLoading(true);
    try {
      const response = await ProductionService.getPainelSetores();
      if (response.success) {
        setPainelData(response.painel);
      } else {
        toast.error(response.error || 'Erro ao carregar dados do painel.');
      }
    } catch (error) {
      toast.error('Erro de comunicação com o servidor.');
      console.error(error);
    } finally {
      if (!painelData) setLoading(false);
    }
  };

  useEffect(() => {
    fetchPainelData();

    // Supabase Realtime Subscription
    const channel = supabase
      .channel('painel-producao-changes')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'itens_demanda' },
        (payload) => {
          console.log('Realtime update received:', payload);
          fetchPainelData();
        }
      )
      .subscribe((status) => {
        if (status === 'SUBSCRIBED') {
          console.log('Connected to Supabase Realtime');
        }
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const handleUpdateProgress = async (item) => {
    setSelectedItem(item);
    setProgressInputs({
      capas_impressas_qtd: 0,
      capas_produzidas_qtd: 0,
      capas_prontas_retirada_qtd: 0,
      miolos_prontos_retirada_qtd: 0,
      expedicao_capas_retiradas_qtd: 0,
      expedicao_miolos_retirados_qtd: 0
    });
    setProgressDialogOpen(true);
  };

  const handleProgressSubmit = async () => {
    if (!selectedItem) return;

    setUpdatingProgress(true);
    try {
      // Filtrar apenas campos com valores maiores que 0
      const updates = {};
      Object.entries(progressInputs).forEach(([field, value]) => {
        const numValue = parseInt(value) || 0;
        if (numValue > 0) {
          updates[field] = numValue;
        }
      });

      if (Object.keys(updates).length === 0) {
        toast.warning('Nenhuma quantidade foi informada.');
        return;
      }

      const result = await ProductionService.updateItemProgress(selectedItem.demanda_id, selectedItem.id, updates);
      if (result.success) {
        toast.success('Progresso atualizado com sucesso!');
        setProgressDialogOpen(false);
        fetchPainelData(); // Refresh data
      } else {
        toast.error(result.error);
      }
    } catch (error) {
      toast.error('Erro ao atualizar progresso.');
    } finally {
      setUpdatingProgress(false);
    }
  };

  const getColumnTitle = (columnKey) => {
    const titles = {
      a_imprimir_capas: 'A Imprimir (Capas)',
      a_produzir_capas: 'A Produzir (Capas)',
      a_agrupar_capas: 'A Agrupar (CPD)',
      a_produzir_miolos: 'A Produzir (Miolos)',
      pronto_expedicao: 'Pronto p/ Expedição',
      em_montagem: 'Em Montagem'
    };
    return titles[columnKey] || columnKey;
  };

  const getColumnIcon = (columnKey) => {
    const icons = {
      a_imprimir_capas: <Clock className="h-4 w-4" />,
      a_produzir_capas: <Package className="h-4 w-4" />,
      a_agrupar_capas: <Package className="h-4 w-4" />,
      a_produzir_miolos: <Package className="h-4 w-4" />,
      pronto_expedicao: <Truck className="h-4 w-4" />,
      em_montagem: <Package className="h-4 w-4" />
    };
    return icons[columnKey] || <Package className="h-4 w-4" />;
  };

  const getColumnColor = (columnKey) => {
    const colors = {
      a_imprimir_capas: 'border-blue-200 bg-blue-50',
      a_produzir_capas: 'border-orange-200 bg-orange-50',
      a_agrupar_capas: 'border-pink-200 bg-pink-50',
      a_produzir_miolos: 'border-purple-200 bg-purple-50',
      pronto_expedicao: 'border-green-200 bg-green-50',
      em_montagem: 'border-indigo-200 bg-indigo-50'
    };
    return colors[columnKey] || 'border-gray-200 bg-gray-50';
  };

  const getPriorityColor = (priority) => {
    if (priority >= 80) return 'border-red-300 bg-red-50';
    if (priority >= 60) return 'border-yellow-300 bg-yellow-50';
    return 'border-gray-300 bg-white';
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('pt-BR');
  };

  const getDaysRemaining = (dateStr) => {
    if (!dateStr) return null;
    const today = new Date();
    const targetDate = new Date(dateStr);
    const diffTime = targetDate - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!painelData) {
    return (
      <div className="container mx-auto p-4">
        <div className="text-center text-muted-foreground">
          <Package className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>Erro ao carregar dados do painel.</p>
        </div>
      </div>
    );
  }

  return (
    <TooltipProvider>
    <div className="container mx-auto p-4 space-y-4">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Painel de Produção</h1>
          <p className="text-muted-foreground mt-1">
            Visão focada no seu setor - {user?.setor_nome || 'Setor não identificado'}
          </p>
        </div>
        <div className="flex flex-wrap gap-4 items-center">
          <Link to="/producao/resumo">
            <Button variant="outline" className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Ver Resumo Geral
            </Button>
          </Link>
          {painelData.setores_pendencias && (
            <div className="flex gap-2 mr-4">
              {Object.entries(painelData.setores_pendencias).map(([setor, pendencia]) => (
                <div key={setor} className="flex flex-col items-center bg-white border rounded-md px-3 py-1 shadow-sm">
                  <span className="text-[10px] uppercase font-bold text-gray-500">{setor}</span>
                  <span className={`text-sm font-bold ${pendencia > 0 ? 'text-blue-600' : 'text-green-600'}`}>
                    {pendencia}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-sm text-muted-foreground">Total de Itens</div>
              <div className="text-2xl font-bold">{painelData.total_itens}</div>
            </div>
            {painelData.demandas_urgentes > 0 && (
              <Badge variant="destructive" className="px-3 py-1">
                <AlertTriangle className="h-3 w-3 mr-1" />
                {painelData.demandas_urgentes} urgentes
              </Badge>
            )}
          </div>
        </div>
      </div>

      {/* Kanban Board */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {Object.entries(painelData.colunas).map(([columnKey, items]) => (
          <div key={columnKey} className="space-y-3">
            <Card className={`border-2 ${getColumnColor(columnKey)}`}>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    {getColumnIcon(columnKey)}
                    {getColumnTitle(columnKey)}
                  </div>
                  <Badge variant="secondary" className="text-xs">
                    {items.length}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[600px]">
                  <div className="space-y-2">
                    {items.map((item) => {
                      const daysRemaining = getDaysRemaining(item.data_entrega);
                      const isUrgent = daysRemaining !== null && daysRemaining <= 3;
                      const isOverdue = daysRemaining !== null && daysRemaining < 0;

                      return (
                        <Card
                          key={item.id}
                          className={`cursor-pointer hover:shadow-md transition-shadow ${getPriorityColor(item.prioridade)}`}
                          onClick={() => handleUpdateProgress(item)}
                        >
                          <CardContent className="p-3">
                            <div className="space-y-2">
                              {/* Header com prioridade e datas */}
                              <div className="flex justify-between items-start">
                                <div className="flex-1">
                                  <div className="font-medium text-sm truncate" title={item.item_descricao}>
                                    {item.item_descricao}
                                  </div>
                                  <div className="text-xs text-muted-foreground">
                                    {item.demanda_nome}
                                  </div>
                                </div>
                                <div className="flex flex-col items-end gap-1">
                                  {isUrgent && (
                                    <Badge variant="destructive" className="text-xs px-1 py-0">
                                      {daysRemaining === 0 ? 'Hoje' : `${Math.abs(daysRemaining)}d`}
                                    </Badge>
                                  )}
                                  {isOverdue && (
                                    <Badge variant="destructive" className="text-xs px-1 py-0">
                                      Atrasado
                                    </Badge>
                                  )}
                                </div>
                              </div>

                              {/* Progress bars - Detalhado */}
                              <div className="space-y-2">
                                <div className="space-y-1">
                                  <div className="flex justify-between text-[10px] uppercase font-bold text-gray-500">
                                    <span>Capas</span>
                                    <span>{item.progresso_capas.prontas_retirada}/{item.quantidade_total}</span>
                                  </div>
                                  <div className="grid grid-cols-3 gap-0.5 h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <div 
                                          className="bg-blue-400 h-full transition-all" 
                                          style={{ width: `${(item.progresso_capas.real_em_producao / item.quantidade_total) * 100}%` }}
                                        />
                                      </TooltipTrigger>
                                      <TooltipContent>Em Produção: {item.progresso_capas.real_em_producao}</TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <div 
                                          className="bg-indigo-400 h-full transition-all" 
                                          style={{ width: `${(item.progresso_capas.real_ficando_prontas / item.quantidade_total) * 100}%` }}
                                        />
                                      </TooltipTrigger>
                                      <TooltipContent>Ficando Prontas: {item.progresso_capas.real_ficando_prontas}</TooltipContent>
                                    </Tooltip>
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <div 
                                          className="bg-green-500 h-full transition-all" 
                                          style={{ width: `${(item.progresso_capas.real_finalizando_expedicao / item.quantidade_total) * 100}%` }}
                                        />
                                      </TooltipTrigger>
                                      <TooltipContent>Finalizando Expedição: {item.progresso_capas.real_finalizando_expedicao}</TooltipContent>
                                    </Tooltip>
                                  </div>
                                </div>

                                <div className="space-y-1">
                                  <div className="flex justify-between text-[10px] uppercase font-bold text-gray-500">
                                    <span>Miolos</span>
                                    <span>{item.progresso_miolos.prontos_retirada}/{item.quantidade_total}</span>
                                  </div>
                                  <div className="flex h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                                    <div 
                                      className="bg-purple-400 h-full transition-all" 
                                      style={{ width: `${(item.progresso_miolos.real_em_producao / item.quantidade_total) * 100}%` }}
                                    />
                                    <div 
                                      className="bg-green-500 h-full transition-all" 
                                      style={{ width: `${(item.progresso_miolos.prontos_retirada / item.quantidade_total) * 100}%` }}
                                    />
                                  </div>
                                </div>
                              </div>

                              {/* Canal e data */}
                              <div className="flex justify-between items-center text-xs text-muted-foreground">
                                <span>{item.canal_venda}</span>
                                <span>{formatDate(item.data_entrega)}</span>
                              </div>

                              {/* Miolo info */}
                              {item.miolo_name && (
                                <div className="text-xs text-muted-foreground">
                                  Miolo: {item.miolo_name}
                                </div>
                              )}
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                    {items.length === 0 && (
                      <div className="text-center text-muted-foreground py-8">
                        <Package className="h-8 w-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">Nenhum item nesta etapa</p>
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        ))}
      </div>

      {/* Progress Update Dialog */}
      <Dialog open={progressDialogOpen} onOpenChange={setProgressDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Atualizar Progresso</DialogTitle>
            <DialogDescription>
              {selectedItem && (
                <>
                  <strong>{selectedItem.item_descricao}</strong><br />
                  Demanda: {selectedItem.demanda_nome}<br />
                  Quantidade total: {selectedItem.quantidade_total}
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {user?.setor_nome === 'CPD' && (
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="text-sm font-medium">Capas Impressas</label>
                  <Badge variant="outline" className="text-[10px]">Estoque: {selectedItem?.estoque_disponivel_impressao}</Badge>
                </div>
                <Input
                  type="number"
                  placeholder="Novas capas impressas"
                  value={progressInputs.capas_impressas_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    capas_impressas_qtd: e.target.value
                  }))}
                />
                <label className="text-sm font-medium">Capas Prontas</label>
                <Input
                  type="number"
                  placeholder="Novas capas prontas"
                  value={progressInputs.capas_prontas_retirada_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    capas_prontas_retirada_qtd: e.target.value
                  }))}
                />
              </div>
            )}

            {user?.setor_nome === 'Capas' && (
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="text-sm font-medium">Capas Produzidas</label>
                  <Badge variant="outline" className="text-[10px]">Estoque: {selectedItem?.estoque_disponivel_capa}</Badge>
                </div>
                <Input
                  type="number"
                  placeholder="Novas capas produzidas"
                  value={progressInputs.capas_produzidas_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    capas_produzidas_qtd: e.target.value
                  }))}
                />
              </div>
            )}

            {user?.setor_nome === 'Miolos' && (
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <label className="text-sm font-medium">Miolos Prontos</label>
                  <Badge variant="outline" className="text-[10px]">Estoque: {selectedItem?.estoque_disponivel_miolo}</Badge>
                </div>
                <Input
                  type="number"
                  placeholder="Novos miolos prontos"
                  value={progressInputs.miolos_prontos_retirada_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    miolos_prontos_retirada_qtd: e.target.value
                  }))}
                />
              </div>
            )}

            {user?.setor_nome === 'Expedição' && (
              <div className="space-y-2">
                <label className="text-sm font-medium">Capas Retiradas</label>
                <Input
                  type="number"
                  placeholder="Capas retiradas"
                  value={progressInputs.expedicao_capas_retiradas_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    expedicao_capas_retiradas_qtd: e.target.value
                  }))}
                />
                <label className="text-sm font-medium">Miolos Retirados</label>
                <Input
                  type="number"
                  placeholder="Miolos retirados"
                  value={progressInputs.expedicao_miolos_retirados_qtd || ''}
                  onChange={(e) => setProgressInputs(prev => ({
                    ...prev,
                    expedicao_miolos_retirados_qtd: e.target.value
                  }))}
                />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setProgressDialogOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={handleProgressSubmit} disabled={updatingProgress}>
              {updatingProgress ? 'Atualizando...' : 'Atualizar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
    </TooltipProvider>
  );
};

export default PainelProducaoPage;
