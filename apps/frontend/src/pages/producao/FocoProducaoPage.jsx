import ProductionHeroCard from '@/components/producao/ProductionHeroCard';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useAuth } from '@/contexts/AuthContext';
import { useLayout } from '@/contexts/LayoutContext';
import ProductionService from '@/services/ProductionService';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

const FocoProducaoPage = () => {
  const { user } = useAuth();
  const [painelData, setPainelData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const { setIsLeftSidebarOpen } = useLayout()

  // Collapse sidebar on mount for this specific page, restore on unmount
  useEffect(() => {
    setIsLeftSidebarOpen(false)
    return () => setIsLeftSidebarOpen(true)
  }, [setIsLeftSidebarOpen])

  const fetchPainelData = async () => {
    // Only set loading on initial load
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
  }, []);

  const sortedItems = useMemo(() => {
    if (!painelData || !painelData.colunas) return { mainLine: [], lateralLine: [] };

    let allItems = [];
    
    // Aggregate items based on user sector
    // If user sector is Miolos, we focus on 'a_produzir_miolos'
    // If user sector is Capas, we focus on 'a_produzir_capas'
    // If unknown, we might show everything (but this page is for operators)
    
    const userSetor = user?.setor_nome;
    let targetColumns = [];

    if (userSetor === 'Miolos') {
      targetColumns = ['a_produzir_miolos'];
    } else if (userSetor === 'Capas') {
      targetColumns = ['a_produzir_capas', 'a_imprimir_capas']; // Include print queue? Maybe just produce.
    } else {
      // Fallback for testing or admin viewing this page
      targetColumns = Object.keys(painelData.colunas);
    }

    targetColumns.forEach(colKey => {
      if (painelData.colunas[colKey]) {
        allItems = [...allItems, ...painelData.colunas[colKey]];
      }
    });

    // Sort and Split
    const mainLine = [];
    const lateralLine = [];

    allItems.forEach(item => {
        // Simple logic to determine if it's lateral (future or specific flag)
        const entrega = new Date(item.data_entrega);
        const hoje = new Date();
        hoje.setHours(0, 0, 0, 0);
        
        const diffTime = entrega - hoje;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        // Regras para Lateral (Normalizadas):
        const tipo = (item.tipo_demanda || '').toUpperCase();
        const modalidade = (item.modalidade_logistica || '').toUpperCase();

        // 1. B2B / EMPRESAS
        // 2. FULFILLMENT
        // 3. ESTOQUE_INTERNO / INTERNO
        // 4. Data entrega > 3 dias
        const isLateralByNature = 
          tipo === 'B2B' || 
          tipo === 'EMPRESAS' ||
          modalidade === 'FULFILLMENT' || 
          tipo === 'ESTOQUE_INTERNO' || 
          tipo === 'INTERNO';
        
        if (isLateralByNature || diffDays > 3) {
            lateralLine.push(item);
        } else {
            mainLine.push(item);
        }
    });

    // Sort Main Line: Priority (High Score first), then Delivery Date (Soonest first)
    mainLine.sort((a, b) => {
        if (b.prioridade !== a.prioridade) return b.prioridade - a.prioridade;
        return new Date(a.data_entrega) - new Date(b.data_entrega);
    });

    // Sort Lateral Line: Readiness (Highest first - easiest to finish), then Priority
    lateralLine.sort((a, b) => {
        // Mocking readiness if not present, assume 0
        const readyA = a.readiness_score || 0;
        const readyB = b.readiness_score || 0;
        return readyB - readyA;
    });

    return { mainLine, lateralLine };
  }, [painelData, user]);

  const handleUpdateProgress = async (item, qty) => {
    setUpdating(true);
    try {
       // Determine field to update based on sector
       const updates = {};
       if (user?.setor_nome === 'Miolos') {
           updates.miolos_prontos_retirada_qtd = qty;
       } else if (user?.setor_nome === 'Capas') {
           updates.capas_produzidas_qtd = qty;
       } else {
           toast.error("Setor não configurado para atualização direta.");
           return;
       }

       // This is an incremental update usually handled by the backend logic or we calculate the new total?
       // The ProductionService.updateItemProgress usually takes absolute values in the inputs object provided in PainelProducaoPage
       // BUT, checking PainelProducaoPage, it sends { miolos_prontos_retirada_qtd: <NEW_VALUE_TO_ADD> } ??
       // Wait, PainelProducaoPage code: 
       // const numValue = parseInt(value) || 0; if (numValue > 0) updates[field] = numValue;
       // ProductionService.updateItemProgress(..., updates).
       // We need to confirm if the API adds or sets. 
       // Usually 'updateItemProgress' in these systems tends to be "Register Production" (Add), but let's be safe.
       // If I look at `PainelProducaoPage.jsx`, the inputs are cleared after submit, and the labels say "Novas capas produzidas".
       // So it implies INCREMENTAL.
       
       const result = await ProductionService.updateItemProgress(item.demanda_id, item.id, updates);
       if (result.success) {
         toast.success(`+${qty} produzido(s)!`);
         fetchPainelData();
       } else {
         toast.error(result.error);
       }
    } catch (error) {
       toast.error('Erro ao atualizar.');
    } finally {
       setUpdating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-screen bg-gray-50">
        <div className="animate-spin rounded-full h-12 w-12 border-b-4 border-orange-600"></div>
      </div>
    );
  }

  const activeItem = sortedItems.mainLine.length > 0 ? sortedItems.mainLine[0] : sortedItems.lateralLine[0];
  const isLateralActive = sortedItems.mainLine.length === 0 && sortedItems.lateralLine.length > 0;
  
  // The Queue (Next 5 items from the active list, excluding the first one)
  const activeList = isLateralActive ? sortedItems.lateralLine : sortedItems.mainLine;
  const nextItems = activeList.slice(1, 6);

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header Minimalista */}
      <header className="bg-white border-b px-6 py-4 flex justify-between items-center shadow-sm">
        <div className="flex items-center gap-4">
           <Link to="/producao">
             <Button variant="ghost" size="icon">
               <ArrowLeft className="h-6 w-6 text-gray-500" />
             </Button>
           </Link>
           <div>
             <h1 className="text-xl font-bold text-gray-900">Modo Foco: {user?.setor_nome || 'Produção'}</h1>
             <p className="text-xs text-gray-500">
               {isLateralActive ? 'Linha Principal Vazia - Aproveite para adiantar!' : 'Mantenha o ritmo na Linha Principal'}
             </p>
           </div>
        </div>
        <div className="flex items-center gap-4">
           <div className="text-right hidden md:block">
              <div className="text-sm text-gray-500">Total na Fila</div>
              <div className="text-xl font-bold text-gray-900">{activeList.length}</div>
           </div>
           <Button variant="outline" size="icon" onClick={fetchPainelData} disabled={loading}>
             <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
           </Button>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
         {/* LEFT / TOP: HERO AREA (2/3 width on desktop) */}
         <section className="lg:col-span-2 flex flex-col justify-center">
            {activeItem ? (
               <ProductionHeroCard 
                 item={activeItem} 
                 userSetor={user?.setor_nome}
                 isLateral={isLateralActive}
                 onUpdateProgress={handleUpdateProgress}
               />
            ) : (
               <div className="h-full flex flex-col items-center justify-center text-center p-12 border-4 border-dashed border-gray-200 rounded-xl">
                  <div className="bg-green-100 p-6 rounded-full mb-6">
                     <RefreshCw className="h-12 w-12 text-green-600" />
                  </div>
                  <h2 className="text-3xl font-bold text-gray-900 mb-2">Tudo Limpo!</h2>
                  <p className="text-xl text-gray-500">Nenhuma demanda pendente para seu setor neste momento.</p>
               </div>
            )}
         </section>

         {/* RIGHT / BOTTOM: UP NEXT QUEUE */}
         <section className="lg:col-span-1 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col h-full">
            <div className="p-4 border-b bg-gray-50 flex justify-between items-center">
               <h3 className="font-bold text-gray-700 uppercase tracking-wide">Na Fila</h3>
               <Badge variant="secondary">{activeList.length - 1 > 0 ? activeList.length - 1 : 0}</Badge>
            </div>
            
            <ScrollArea className="flex-1">
               <div className="divide-y divide-gray-100">
                  {nextItems.map((item, idx) => (
                     <div key={item.id} className="p-4 hover:bg-gray-50 transition-colors">
                        <div className="flex justify-between items-start mb-1">
                           <span className="font-bold text-gray-900 line-clamp-2">{item.item_descricao}</span>
                           <span className="text-sm font-bold text-gray-400">#{idx + 2}</span>
                        </div>
                        <div className="flex justify-between items-center mt-2">
                           <div className="text-xs text-gray-500">
                              {item.miolo_name || 'Item padrão'}
                           </div>
                           <Badge variant="outline" className="text-xs border-gray-200 text-gray-600">
                              Qtd: {item.quantidade_total}
                           </Badge>
                        </div>
                     </div>
                  ))}
                  {nextItems.length === 0 && activeItem && (
                     <div className="p-8 text-center text-gray-400 text-sm">
                        Final da fila.
                     </div>
                  )}
                  {nextItems.length === 0 && !activeItem && (
                     <div className="p-8 text-center text-gray-400 text-sm">
                        -
                     </div>
                  )}
               </div>
            </ScrollArea>
         </section>
      </main>
    </div>
  );
};

export default FocoProducaoPage;
