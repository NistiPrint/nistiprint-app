import IncrementalInput from '@/components/producao/IncrementalInput';
import PartialCollectionModal from '@/components/producao/PartialCollectionModal';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAuth } from '@/contexts/AuthContext';
import { useLayout } from '@/contexts/LayoutContext';
import useLocalAgent from '@/hooks/useLocalAgent';
import usePermissionsHook from '@/hooks/usePermissions';
import useDebounce from '@/lib/hooks/useDebounce';
import { supabase } from '@/lib/supabase';
import { ArrowLeft, Calendar, CheckCircle, Flame, List, Package, Printer, Save, Search, TrendingUp, Truck, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

function DemandaDashboardPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { canEditField, canExecuteAction } = usePermissionsHook();
  const { isAgentOnline, printMappedFile, getMappedFileForProduct } = useLocalAgent();
  const [demanda, setDemanda] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { setIsLeftSidebarOpen } = useLayout()

  // Collapse sidebar on mount for this specific page, restore on unmount
  useEffect(() => {
    setIsLeftSidebarOpen(false)
    return () => setIsLeftSidebarOpen(true)
  }, [setIsLeftSidebarOpen])
  
  // Batch Editing State
  const [pendingChanges, setPendingChanges] = useState({});
  const [isSaving, setIsSaving] = useState(false);

  const [viewMode, setViewMode] = useState("producao");
  const [statusFilter, setStatusFilter] = useState("ativos"); // ativos, finalizados
  const [searchQuery, setSearchQuery] = useState('');

  // States for Partial Quantities
  const [partialQuantities, setPartialQuantities] = useState({});
  const [isPartialCollectionModalOpen, setIsPartialCollectionModalOpen] = useState(false);

  const debouncedSearchQuery = useDebounce(searchQuery, 300);

  const hasPendingChanges = Object.keys(pendingChanges).length > 0;

  const fetchDemanda = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const response = await fetch(`/api/v2/demanda_producao/${id}`, {
        headers: { 'Accept': 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      if (data.success) {
        let updatedDemanda = data.demanda;
        
        // Mesclar mudanças locais nos itens
        if (updatedDemanda.itens && Object.keys(pendingChangesRef.current).length > 0) {
          const pending = pendingChangesRef.current;
          updatedDemanda.itens = updatedDemanda.itens.map(item => {
            if (pending[item.id]) {
              return { ...item, ...pending[item.id] };
            }
            return item;
          });
        }
        
        setDemanda(updatedDemanda);
      } else {
        throw new Error(data.message || 'Erro ao carregar demanda');
      }
    } catch (e) {
      if (!silent) setError(e.message);
      console.error(e);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [id]);

  // Ref para pendingChanges para acesso seguro dentro do fetch sem causar re-renders do useCallback
  const pendingChangesRef = useRef(pendingChanges);
  useEffect(() => {
    pendingChangesRef.current = pendingChanges;
  }, [pendingChanges]);

  useEffect(() => {
    fetchDemanda();

    // Supabase Realtime Listener para esta demanda específica ou seus itens
    const channel = supabase
      .channel(`demanda-dashboard-${id}`)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'demandas_producao', filter: `id=eq.${id}` },
        () => {
           if (!isSaving) fetchDemanda(true);
        }
      )
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'itens_demanda', filter: `demanda_id=eq.${id}` },
        () => {
           if (!isSaving) fetchDemanda(true);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [id, fetchDemanda, isSaving]);

  // Itens filtrados e com mudanças locais aplicadas
  const allProcessedItems = useMemo(() => {
    if (!demanda?.itens) return [];
    return demanda.itens.map(item => {
      const changes = pendingChanges[item.id];
      return changes ? { ...item, ...changes } : item;
    });
  }, [demanda?.itens, pendingChanges]);

  const filteredItems = useMemo(() => {
    const query = debouncedSearchQuery.toLowerCase();
    const items = allProcessedItems.filter(item =>
        item.item_descricao.toLowerCase().includes(query) ||
        item.miolo_name?.toLowerCase().includes(query) ||
        item.variacao?.toLowerCase().includes(query)
    );

    if (statusFilter === 'ativos') {
        // Itens que ainda tem saldo para finalizar
        return items.filter(i => {
            const finalizados = Math.min(i.expedicao_capas_retiradas_qtd || 0, i.expedicao_miolos_retirados_qtd || 0);
            return i.status_item !== 'Concluído' && finalizados < i.quantidade_total;
        });
    } else {
        // Itens que tiveram a quantidade total finalizada
        return items.filter(i => {
            const finalizados = Math.min(i.expedicao_capas_retiradas_qtd || 0, i.expedicao_miolos_retirados_qtd || 0);
            return finalizados >= i.quantidade_total;
        });
    }
  }, [allProcessedItems, debouncedSearchQuery, statusFilter]);

  const handleLocalChange = useCallback((itemId, fieldName, delta) => {
    setPendingChanges(prev => {
      const itemChanges = prev[itemId] || {};
      const itemOriginal = demanda.itens.find(i => String(i.id) === String(itemId));
      
      if (!itemOriginal) return prev;

      const currentValue = itemChanges[fieldName] !== undefined ? itemChanges[fieldName] : (itemOriginal[fieldName] || 0);
      const newValue = currentValue + delta;
      
      return {
        ...prev,
        [itemId]: { ...itemChanges, [fieldName]: newValue }
      };
    });
    return Promise.resolve();
  }, [demanda]);

  const handleBulkSave = async () => {
    if (!hasPendingChanges) return;
    setIsSaving(true);
    try {
      const itemIds = Object.keys(pendingChanges);
      const updates = itemIds.map(itemId => {
        const changes = pendingChanges[itemId];
        const originalItem = demanda.itens.find(i => String(i.id) === String(itemId));
        
        if (!originalItem) return null;

        const producaoIncremental = {};
        Object.keys(changes).forEach(field => {
          const delta = changes[field] - (originalItem[field] || 0);
          if (delta !== 0) producaoIncremental[field] = delta;
        });

        if (Object.keys(producaoIncremental).length === 0) return null;

        return {
          item_id: itemId,
          producao_incremental: producaoIncremental
        };
      }).filter(Boolean);

      if (updates.length === 0) {
        setPendingChanges({});
        return;
      }

      console.log(updates)

      const response = await fetch(`/api/v2/demanda_producao/${id}/itens/registrar-producao-lote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'Falha ao salvar lote de itens');
      }

      console.log(response)

      toast.success('Alterações salvas!');
      setPendingChanges({});
      await fetchDemanda();
    } catch (e) {
      toast.error(`Erro: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancelChanges = () => setPendingChanges({});

  const handleFinalizeWithQuantity = async (item, quantity) => {
      const faltanteCapas = item.quantidade_total - (item.expedicao_capas_retiradas_qtd || 0);
      const faltanteMiolos = item.quantidade_total - (item.expedicao_miolos_retirados_qtd || 0);
      const maxFaltante = Math.min(faltanteCapas, faltanteMiolos);

      // Se a quantidade for maior que o faltante, usar o máximo faltante
      const adjustedQuantity = Math.min(quantity, maxFaltante);

      if (adjustedQuantity <= 0) {
          toast.error(`Nenhuma unidade disponível para finalizar.`);
          return;
      }

      if (!confirm(`Finalizar ${adjustedQuantity} unidades deste item?`)) return;

      try {
          const response = await fetch(`/api/v2/demanda_producao/${id}/item/${item.id}/finalizar-parcial`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ quantidade_parcial: adjustedQuantity })
          });
          const data = await response.json();
          if (data.success) {
              toast.success(`${adjustedQuantity} unidades finalizadas!`);
              // Limpar a quantidade parcial local após sucesso
              setPartialQuantities(prev => {
                const newPartials = { ...prev };
                delete newPartials[item.id];
                return newPartials;
              });
              fetchDemanda();
          } else toast.error(data.message);
      } catch (e) { toast.error(e.message); }
  };

  const handleRevertFinalization = async (item) => {
      if (!confirm(`Tem certeza que deseja reverter a finalização deste item? O status voltará para "Em Andamento"`)) return;

      try {
          const response = await fetch(`/api/v2/demanda_producao/${id}/item/${item.id}/reverter-finalizacao`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' }
          });
          const data = await response.json();
          if (data.success) {
              toast.success(data.message);
              fetchDemanda();
          } else toast.error(data.message);
      } catch (e) { toast.error(e.message); }
  };

  const handleCollectDemand = () => {
      setIsPartialCollectionModalOpen(true);
  };

  const handleConfirmCollection = async (demandaId, quantity) => {
      try {
          const response = await fetch(`/api/v2/demanda_producao/${demandaId}/coletar`, { 
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ quantidade_coletar: quantity })
          });
          const data = await response.json();
          if (data.success) {
              toast.success('Coleta registrada!');
              fetchDemanda();
          } else {
              toast.error(data.message);
          }
      } catch (e) { toast.error(e.message); }
  };

  const handlePrintDemanda = async (mode) => {
    if (!confirm(`Enviar ${mode === 'full' ? 'TODAS' : 'PENDENTES'} para impressão?`)) return;
    try {
        const response = await fetch(`/api/v2/printing/demanda/${id}/print?mode=${mode}`, { method: 'POST' });
        const data = await response.json();
        if (response.ok) {
            toast.success(`Jobs criados: ${data.count}`);
        } else {
            toast.error(data.error || 'Erro ao criar jobs');
        }
    } catch (e) { toast.error(e.message); }
  };

  const handlePrintItem = async (item, mode) => {
    // Quantidade a imprimir
    let quantity = item.quantidade_total;
    if (mode === 'balance') {
        quantity = Math.max(0, item.quantidade_total - (item.capas_impressas_qtd || 0));
    }

    if (quantity <= 0) {
        toast.info("Nada a imprimir.");
        return;
    }

    // Tentar impressão local se agente estiver online
    if (isAgentOnline && item.produto_id) {
        try {
            const mappedFile = await getMappedFileForProduct(item.produto_id);
            if (mappedFile) {
                if (confirm(`Arquivo local encontrado: ${mappedFile.file_path}\n\nDeseja imprimir ${quantity} cópias localmente?`)) {
                    try {
                        await printMappedFile(item.produto_id, quantity);
                        toast.success(`Enviado para impressora local: ${quantity} cópias`);
                    } catch (printError) {
                        console.error("Erro na impressão local:", printError);
                        // Extrai mensagem de erro detalhada se disponível
                        const errorMsg = printError.response?.data?.detail || printError.message || "Erro desconhecido";
                        toast.error(`Erro ao imprimir localmente: ${errorMsg}`);
                    }
                    return; // Interrompe fluxo para não tentar nuvem (pois o usuário escolheu local)
                }
            }
        } catch (localError) {
            console.warn("Falha na verificação local (ignorado), tentando nuvem...", localError);
        }
    }

    // Fallback para impressão via Nuvem (Print Node / Server)
    try {
        const response = await fetch(`/api/v2/printing/item/${item.id}/print?mode=${mode}`, { method: 'POST' });
        const data = await response.json();
        if (response.ok) {
            toast.success(`Jobs criados (Nuvem): ${data.count}`);
        } else {
            toast.error(data.error || 'Erro ao criar jobs');
        }
    } catch (e) { toast.error(e.message); }
  };

  const fieldMapping = {
    'capas_impressas': 'capas_impressas_qtd',
    'capas_produzidas': 'capas_produzidas_qtd',
    'capas_prontas': 'capas_prontas_retirada_qtd',
    'miolos_prontos': 'miolos_prontos_retirada_qtd',
    'expedicao_capas': 'expedicao_capas_retiradas_qtd',
    'expedicao_miolos': 'expedicao_miolos_retirados_qtd'
  };

  const columnTitles = {
    'produto_miolo': 'Produto / Miolo',
    'total': 'Total',
    'capas_impressas': 'Capas Imp.',
    'capas_produzidas': 'Capas Prod.',
    'capas_prontas': 'Capas Prontas',
    'miolos_prontos': 'Miolos Prontos',
    'expedicao_capas': 'Exp. Capas',
    'expedicao_miolos': 'Exp. Miolos',
    'acoes': 'Finalização'
  };

  const columnClasses = {
    'capas_impressas': 'text-center bg-gray-50/50 w-24',
    'capas_produzidas': 'text-center bg-orange-50/50 w-24',
    'capas_prontas': 'text-center bg-blue-50/50 w-24',
    'miolos_prontos': 'text-center bg-blue-50/50 w-24',
    'expedicao_capas': 'text-center bg-green-50/50 w-24',
    'expedicao_miolos': 'text-center bg-green-50/50 w-24',
    'acoes': 'text-right w-24'
  };

  const getViewColumns = () => {
    switch (viewMode) {
      case 'capas_miolos':
        return ['produto_miolo', 'total', 'capas_impressas', 'capas_produzidas', 'capas_prontas', 'miolos_prontos'];
      case 'expedicao':
        return ['produto_miolo', 'total', 'capas_prontas', 'miolos_prontos', 'expedicao_capas', 'expedicao_miolos', 'acoes'];
      case 'producao':
      default:
        return ['produto_miolo', 'total', 'capas_impressas', 'capas_produzidas', 'capas_prontas', 'miolos_prontos', 'expedicao_capas', 'expedicao_miolos', 'acoes'];
    }
  };

  const activeColumns = getViewColumns();

  const handleFillAllForColumn = (columnName) => {
      const fieldName = fieldMapping[columnName];
      const newPending = { ...pendingChanges };
      filteredItems.forEach(item => {
          if ((item[fieldName] || 0) !== item.quantidade_total && item.status_item !== 'Concluído') {
             newPending[item.id] = { ...(newPending[item.id] || {}), [fieldName]: item.quantidade_total };
          }
      });
      setPendingChanges(newPending);
      toast.info(`Coluna preenchida localmente.`);
  };

  const getMaxValueForField = (item, fieldName) => {
    switch (fieldName) {
      case 'capas_impressas_qtd': return item.quantidade_total;
      case 'capas_produzidas_qtd': return Math.max(0, (item.capas_impressas_qtd || 0));
      case 'capas_prontas_retirada_qtd': return Math.max(0, (item.capas_produzidas_qtd || 0));
      case 'miolos_prontos_retirada_qtd': return item.quantidade_total;
      case 'expedicao_capas_retiradas_qtd': return Math.max(0, (item.capas_prontas_retirada_qtd || 0));
      case 'expedicao_miolos_retirados_qtd': return Math.max(0, (item.miolos_prontos_retirada_qtd || 0));
      default: return undefined;
    }
  };

  const renderCell = (item, columnName) => {
    if (columnName === 'produto_miolo') {
      const isReadyForExpedition = item.quantidade_total > 0 &&
                                   item.capas_prontas_retirada_qtd >= item.quantidade_total &&
                                   item.miolos_prontos_retirada_qtd >= item.quantidade_total;
      return (
        <TableCell key="produto_miolo" className="max-w-[300px] group relative">
          <div className="flex justify-between items-start">
            <div>
                <div className="font-medium text-sm leading-tight mb-1" title={item.item_descricao}>
                  {item.produto_id ? (
                    <Link to={`/produtos/${item.produto_id}/editar`} className="text-blue-600 hover:underline">
                      {item.item_descricao}
                    </Link>
                  ) : (
                    item.item_descricao
                  )}
                </div>
                <div className="text-xs text-muted-foreground leading-tight">
                    <span className="font-semibold text-gray-500">Var:</span> {item.variacao || item.variation || '-'} <br/>
                    <span className="font-semibold text-gray-500">Mio: </span>
                    {item.id_produto_miolo ? (
                      <Link to={`/produtos/${item.id_produto_miolo}/editar`} className="text-blue-600 hover:underline">
                        {item.miolo_name || item.miolo || '-'}
                      </Link>
                    ) : (
                      item.miolo_name || item.miolo || '-'
                    )}
                </div>
                {isReadyForExpedition && item.status_item !== 'Concluído' && <Badge variant="outline" className="mt-1 text-[9px] h-4 border-indigo-500 text-indigo-700 bg-indigo-50 uppercase">Pronto Expedição</Badge>}
            </div>

            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-6 w-6"><Printer className="h-4 w-4 text-gray-500 hover:text-black" /></Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                        <DropdownMenuItem onClick={() => handlePrintItem(item, 'full')}>Imprimir Tudo ({item.quantidade_total})</DropdownMenuItem>
                        <DropdownMenuItem onClick={() => handlePrintItem(item, 'balance')}>Imprimir Faltantes ({Math.max(0, item.quantidade_total - (item.capas_impressas_qtd || 0))})</DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
          </div>
        </TableCell>
      );
    }

    if (columnName === 'total') return <TableCell key={columnName} className="text-center font-bold text-sm">{item.quantidade_total}</TableCell>;

    if (columnName === 'acoes') {
      const finalizados = Math.min(item.expedicao_capas_retiradas_qtd || 0, item.expedicao_miolos_retirados_qtd || 0);
      const isTotalmenteFinalizado = item.status_item === 'Concluído' || finalizados >= item.quantidade_total;

      if (isTotalmenteFinalizado) {
        // Verificar se o usuário tem permissão para reverter finalização
        const canRevert = user?.is_admin || canExecuteAction('revert_finalize_item');

        return (
          <TableCell key={columnName} className="text-right">
            <div className="flex items-center justify-end gap-2">
              <Badge className="bg-green-100 text-green-700 border-green-200">
                {item.quantidade_total}/{item.quantidade_total} FINALIZADO
              </Badge>
              {canRevert && (
                <Button
                  variant="outline"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => handleRevertFinalization(item)}
                  title="Reverter Finalização"
                >
                  <X className="h-3.5 w-3.5 text-red-600" />
                </Button>
              )}
            </div>
          </TableCell>
        );
      }

      if (!user?.is_admin && !canExecuteAction('finalize_item')) {
        return <TableCell key={columnName} className="text-right">-</TableCell>;
      }

      const faltanteCapas = item.quantidade_total - (item.expedicao_capas_retiradas_qtd || 0);
      const faltanteMiolos = item.quantidade_total - (item.expedicao_miolos_retirados_qtd || 0);
      const saldoRestante = Math.min(faltanteCapas, faltanteMiolos);
      const currentValue = partialQuantities[item.id] !== undefined ? partialQuantities[item.id] : '';

      return (
        <TableCell key={columnName} className="text-right">
          <div className="flex flex-col items-end gap-1">
            {finalizados > 0 && (
                <span className="text-[10px] text-green-600 font-bold">Já finalizado: {finalizados}</span>
            )}
            <div className="flex justify-end gap-1 items-center">
              <Input
                type="number"
                min="1"
                max={saldoRestante}
                value={currentValue}
                onChange={(e) => {
                  const value = e.target.value === '' ? '' : parseInt(e.target.value) || 0;
                  setPartialQuantities(prev => ({ ...prev, [item.id]: value }));
                }}
                className="w-16 h-7 text-xs"
                title={`Faltam: ${saldoRestante}`}
                placeholder={saldoRestante.toString()}
              />
              <Button
                variant="secondary"
                size="icon"
                className="h-7 w-7"
                onClick={() => {
                  // Se o valor estiver vazio, finaliza o saldo restante
                  const quantityToFinalize = currentValue === '' ? saldoRestante : currentValue;
                  handleFinalizeWithQuantity(item, quantityToFinalize);
                }}
                title={`Finalizar ${currentValue === '' ? saldoRestante : currentValue} unidades`}
              >
                <CheckCircle className="h-3.5 w-3.5 text-green-600" />
              </Button>
            </div>
          </div>
        </TableCell>
      );
    }

    const fieldName = fieldMapping[columnName];
    // Se o item estiver finalizado, não permite edição
    const canEdit = (user?.is_admin || canEditField(fieldName)) && item.status_item !== 'Concluído';
    const maxValue = getMaxValueForField(item, fieldName);

    // Identificar estoque disponível para esta coluna
    let estoqueDisponivel = null;
    if (columnName === 'miolos_prontos') estoqueDisponivel = item.estoque_disponivel_miolo;
    if (columnName === 'capas_produzidas') estoqueDisponivel = item.estoque_disponivel_capa;
    if (columnName === 'capas_impressas') estoqueDisponivel = item.estoque_disponivel_impressao;

    return (
      <TableCell key={columnName} className={`${columnClasses[columnName]}`}>
        <div className="flex flex-col items-center gap-1">
          <IncrementalInput
            currentValue={item[fieldName] || 0}
            fieldName={fieldName}
            itemId={item.id}
            onSave={handleLocalChange}
            disabled={!canEdit}
            maxValue={maxValue}
            totalQuantity={item.quantidade_total}
          />
          {estoqueDisponivel !== null && (
            <div className={`text-[9px] font-bold px-1 rounded ${estoqueDisponivel > 0 ? 'text-green-600 bg-green-50' : 'text-gray-400 bg-gray-50'}`}>
              Est: {estoqueDisponivel}
            </div>
          )}
        </div>
      </TableCell>
    );
  };

  if (loading && !demanda) return <div className="text-center py-8">Carregando Dashboard...</div>;
  if (error) return <div className="text-center py-8 text-red-500">Erro: {error}</div>;
  if (!demanda) return <div className="text-center py-8">Demanda não encontrada.</div>;

  const diasRestantes = Math.ceil((new Date(demanda.data_entrega) - new Date()) / (1000 * 60 * 60 * 24));
  const isUrgente = diasRestantes <= 3;

  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl relative">
      {/* Botão Flutuante */}
      {hasPendingChanges && (
        <div className="fixed bottom-8 right-8 z-50 bg-white p-4 rounded-lg shadow-2xl border-2 border-primary animate-in fade-in slide-in-from-bottom-4 flex items-center gap-4">
          <div className="flex flex-col"><span className="text-sm font-bold">Alterações Pendentes</span><span className="text-xs text-muted-foreground">{Object.keys(pendingChanges).length} itens</span></div>
          <div className="flex gap-2 border-l pl-4">
            <Button variant="outline" size="sm" onClick={handleCancelChanges} disabled={isSaving}><X className="h-4 w-4 mr-1" /> Descartar</Button>
            <Button size="sm" onClick={handleBulkSave} disabled={isSaving}>{isSaving ? 'Salvando...' : <><Save className="h-4 w-4 mr-1" /> Salvar Tudo</>}</Button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900">{demanda.nome}</h1>
            {demanda.is_flex && (
              <Badge className="bg-purple-600 text-white border-none animate-pulse">
                <Flame className="w-3 h-3 mr-1" />
                FLEX
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">{demanda.status}</Badge>
            {isUrgente && <Badge className="bg-red-100 text-red-700 border-red-300">Urgente</Badge>}
            <span className="text-xs text-muted-foreground ml-2">{demanda.canal_venda_nome}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Link to="/producao/impressao"><Button variant="outline" size="icon" title="Fila de Impressão"><List className="h-4 w-4" /></Button></Link>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
               <Button variant="outline" title="Impressão em Massa"><Printer className="h-4 w-4 mr-2" /> Imprimir</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuItem onClick={() => handlePrintDemanda('full')}>Imprimir Todos (Completo)</DropdownMenuItem>
                <DropdownMenuItem onClick={() => handlePrintDemanda('balance')}>Imprimir Pendentes (Saldo)</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <Link to="/producao/demanda"><Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button></Link>
          {demanda.status !== 'Coletado' && canExecuteAction('collect_demand') && (
              <Button onClick={handleCollectDemand} className="bg-green-600 hover:bg-green-700"><Truck className="mr-2 h-4 w-4" /> Coletar</Button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="p-3 flex items-center gap-3">
            <TrendingUp className="h-5 w-5 text-blue-500" />
            <div className="flex-1">
                <p className="text-[10px] text-muted-foreground uppercase font-bold">Progresso</p>
                <div className="flex items-center justify-between"><span className="text-sm font-bold">{demanda.progresso_percentual}%</span><span className="text-[10px]">{demanda.itens_concluidos}/{demanda.total_itens}</span></div>
                <Progress value={demanda.progresso_percentual} className="h-1.5 mt-1" />
            </div>
        </Card>
        <Card className="p-3 flex items-center gap-3">
            <Calendar className={`h-5 w-5 ${isUrgente ? 'text-red-500' : 'text-green-500'}`} />
            <div>
                <p className="text-[10px] text-muted-foreground uppercase font-bold">Entrega</p>
                <p className="text-sm font-bold">{new Date(demanda.data_entrega).toLocaleDateString('pt-BR')}</p>
            </div>
        </Card>
        <Card className="p-3 flex items-center gap-3">
            <Package className="h-5 w-5 text-purple-500" />
            <div>
                <p className="text-[10px] text-muted-foreground uppercase font-bold">Total Unidades</p>
                <p className="text-sm font-bold">{demanda.total_quantidade}</p>
            </div>
        </Card>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input placeholder="Buscar itens..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} className="pl-9 h-full" />
        </div>
      </div>

      <div className="flex items-center justify-between mb-4 gap-4">
        <div className="flex gap-4 items-end">
            <div className="flex flex-col gap-1">
                <Label className="text-xs text-muted-foreground">Ver como</Label>
                <div className="flex gap-1">
                    <Button variant={viewMode === 'producao' ? 'default' : 'outline'} size="sm" onClick={() => setViewMode('producao')}>Geral</Button>
                    <Button variant={viewMode === 'capas_miolos' ? 'default' : 'outline'} size="sm" onClick={() => setViewMode('capas_miolos')}>Capas / Miolos</Button>
                    <Button variant={viewMode === 'expedicao' ? 'default' : 'outline'} size="sm" onClick={() => setViewMode('expedicao')}>Expedição</Button>
                </div>
            </div>

            <div className="flex flex-col gap-1 border-l pl-4">
                <Label className="text-xs text-muted-foreground">Status do Item</Label>
                <div className="flex gap-1">
                    <Button variant={statusFilter === 'ativos' ? 'default' : 'outline'} size="sm" onClick={() => setStatusFilter('ativos')}>Em Andamento</Button>
                    <Button variant={statusFilter === 'finalizados' ? 'default' : 'outline'} size="sm" onClick={() => setStatusFilter('finalizados')}>Finalizados</Button>
                </div>
            </div>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
                <TableRow>
                    {activeColumns.map(col => (
                        <TableHead key={col} className={columnClasses[col]}>
                            <div className="flex items-center justify-between">
                                <span>{columnTitles[col]}</span>
                                {['capas_impressas', 'capas_produzidas', 'capas_prontas', 'miolos_prontos', 'expedicao_capas', 'expedicao_miolos'].includes(col) &&
                                 statusFilter === 'ativos' &&
                                 (user?.is_admin || canEditField(fieldMapping[col])) && (
                                    <Button variant="ghost" size="icon" className="h-4 w-4" onClick={() => handleFillAllForColumn(col)}><CheckCircle className="h-3 w-3 text-green-600"/></Button>
                                )}
                            </div>
                        </TableHead>
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {filteredItems.length === 0 ? (
                    <TableRow><TableCell colSpan={activeColumns.length} className="text-center py-8 text-muted-foreground font-medium">
                        {statusFilter === 'ativos' ? 'Nenhum item em andamento.' : 'Nenhum item com quantidade total finalizada.'}
                    </TableCell></TableRow>
                ) : (
                    filteredItems.map(item => (
                        <TableRow key={item.id}>
                            {activeColumns.map(col => renderCell(item, col))}
                        </TableRow>
                    ))
                )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      
      <PartialCollectionModal 
          isOpen={isPartialCollectionModalOpen}
          onClose={() => setIsPartialCollectionModalOpen(false)}
          demandaId={demanda.id}
          onConfirm={handleConfirmCollection}
      />
    </div>
  );
}

export default DemandaDashboardPage;
