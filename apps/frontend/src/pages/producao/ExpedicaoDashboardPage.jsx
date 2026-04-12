import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import ProductionService from '@/services/ProductionService';
import { ArrowRight, CheckCircle2, Loader2, Package } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

const ExpedicaoDashboardPage = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterTrilha, setFilterTrilha] = useState('ALL');

  const fetchData = async () => {
    setLoading(true);
    try {
      const response = await ProductionService.getConsolidadoProducao({ agrupado: false });
      if (response.success) {
        setItems(response.data || []);
      } else {
        toast.error('Erro ao carregar dados da expedição.');
      }
    } catch (error) {
      console.error(error);
      toast.error('Erro de comunicação com o servidor.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const { matches, pending, closing } = useMemo(() => {
    let currentItems = items;
    if (filterTrilha !== 'ALL') {
      currentItems = items.filter(item => item.trilha === filterTrilha);
    }

    const matches = [];
    const pending = [];
    const closing = [];

    currentItems.forEach(item => {
      const hasExpedicao = (item.expedicao_capas_retiradas_qtd > 0 || item.expedicao_miolos_retirados_qtd > 0);
      
      if (item.match_disponivel > 0) {
        matches.push(item);
      } else if (hasExpedicao) {
        closing.push(item);
      } else {
        pending.push(item);
      }
    });

    // Sort matches: High priority first
    matches.sort((a, b) => {
        // Main line before Lateral
        if (a.trilha === 'PRINCIPAL' && b.trilha !== 'PRINCIPAL') return -1;
        if (a.trilha !== 'PRINCIPAL' && b.trilha === 'PRINCIPAL') return 1;
        return 0;
    });

    return { matches, pending, closing };
  }, [items, filterTrilha]);

  const handleRetirada = async (demandaId, itemId, maxMatch) => {
    if (maxMatch <= 0) return;
    
    const qty = prompt(`Quantidade a retirar (Máximo: ${maxMatch}):`, maxMatch);
    const quantidade = parseInt(qty);
    
    if (isNaN(quantidade) || quantidade <= 0) return;
    if (quantidade > maxMatch) {
      toast.error('Quantidade superior ao match disponível.');
      return;
    }

    try {
      const response = await ProductionService.registrarRetiradaExpedicao(demandaId, itemId, quantidade);
      if (response.success) {
        toast.success('Retirada registrada!');
        fetchData();
      } else {
        toast.error(response.message);
      }
    } catch (error) {
      toast.error('Erro ao registrar retirada.');
    }
  };

  if (loading && items.length === 0) {
    return <div className="flex justify-center items-center h-screen"><Loader2 className="animate-spin h-8 w-8" /></div>;
  }

  const MatchCard = ({ item }) => (
    <Card className="border-4 border-green-500 shadow-lg bg-green-50/30 transform hover:scale-[1.01] transition-all duration-200">
      <CardContent className="p-6">
         <div className="flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex-1">
               <div className="flex items-center gap-2 mb-1">
                  <Badge className="bg-green-600 hover:bg-green-700 text-white border-none animate-pulse">
                     PRONTO PARA MONTAGEM
                  </Badge>
                  {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-teal-600 border-teal-600">LATERAL</Badge>}
               </div>
               <h3 className="text-2xl font-black text-gray-900">{item.item_nome}</h3>
               <div className="text-sm text-gray-600 font-medium mt-1">
                  {item.demanda_nome} <span className="text-gray-400 mx-2">|</span> SKU: {item.sku}
               </div>
            </div>

            <div className="flex flex-col items-center justify-center bg-white p-4 rounded-xl border border-green-200 shadow-sm min-w-[150px]">
               <div className="text-4xl font-black text-green-600">{item.match_disponivel}</div>
               <div className="text-xs font-bold text-gray-400 uppercase tracking-widest">Unidades</div>
            </div>

            <div>
               <Button 
                  size="lg" 
                  className="h-16 px-8 text-xl font-bold bg-green-600 hover:bg-green-700 shadow-md w-full md:w-auto"
                  onClick={() => handleRetirada(item.demanda_id, item.item_id, item.match_disponivel)}
               >
                  RETIRAR AGORA <ArrowRight className="ml-2 h-6 w-6" />
               </Button>
            </div>
         </div>
      </CardContent>
    </Card>
  );

  const PendingCard = ({ item }) => (
    <Card className="border-l-4 border-l-amber-400 opacity-90 hover:opacity-100 transition-opacity">
       <CardContent className="p-4">
          <div className="flex justify-between items-start gap-4">
             <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                   <Badge variant="outline" className="text-xs font-normal text-gray-500 border-gray-300">Aguardando</Badge>
                   {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-[10px] text-teal-600 border-teal-200">LATERAL</Badge>}
                </div>
                <h4 className="font-bold text-gray-700">{item.item_nome}</h4>
                <div className="text-xs text-gray-500">{item.demanda_nome}</div>
             </div>

             <div className="flex gap-4 text-xs font-medium">
                <div className={`flex flex-col items-center ${item.capas_prontas >= item.qtd_total ? 'text-green-600' : 'text-amber-600'}`}>
                   <span>Capas</span>
                   <span className="text-lg font-bold">{item.capas_prontas}/{item.qtd_total}</span>
                </div>
                <div className="w-px bg-gray-200 h-full"></div>
                <div className={`flex flex-col items-center ${item.miolos_prontos >= item.qtd_total ? 'text-green-600' : 'text-amber-600'}`}>
                   <span>Miolos</span>
                   <span className="text-lg font-bold">{item.miolos_prontos}/{item.qtd_total}</span>
                </div>
             </div>
          </div>
       </CardContent>
    </Card>
  );

  const ClosingCard = ({ item }) => {
    const expedidas = Math.min(item.expedicao_capas_retiradas_qtd || 0, item.expedicao_miolos_retirados_qtd || 0);
    const progresso = (expedidas / item.qtd_total) * 100;
    const isCompleto = expedidas >= item.qtd_total;

    // Determine badge style and text based on actual status_item
    const getStatusBadge = () => {
      if (item.status_item === 'Concluído') {
        return { text: 'CONCLUÍDO', className: 'bg-green-600 hover:bg-green-700 text-white border-none' };
      } else if (item.status_item === 'Fechando') {
        return { text: 'FECHANDO', className: 'bg-orange-500 hover:bg-orange-600 text-white border-none' };
      } else {
        return { text: 'EM FECHAMENTO', className: 'bg-blue-600 hover:bg-blue-700 text-white border-none' };
      }
    };

    const statusBadge = getStatusBadge();

    return (
      <Card className={`border-l-4 ${item.status_item === 'Concluído' ? 'border-l-green-500 bg-green-50/20' : item.status_item === 'Fechando' ? 'border-l-orange-500 bg-orange-50/20' : 'border-l-blue-500 bg-blue-50/20'} opacity-90 hover:opacity-100 transition-opacity`}>
         <CardContent className="p-4">
            <div className="flex justify-between items-start gap-4">
               <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                     <Badge className={statusBadge.className}>
                        {statusBadge.text}
                     </Badge>
                     {item.trilha === 'LATERAL' && <Badge variant="outline" className="text-[10px] text-teal-600 border-teal-200">LATERAL</Badge>}
                  </div>
                  <h4 className="font-bold text-gray-700">{item.item_nome}</h4>
                  <div className="text-xs text-gray-500">{item.demanda_nome}</div>
               </div>

               <div className="flex flex-col items-center gap-2">
                  <div className="text-center">
                     <div className={`text-2xl font-bold ${item.status_item === 'Concluído' ? 'text-green-600' : item.status_item === 'Fechando' ? 'text-orange-600' : 'text-blue-600'}`}>{expedidas}/{item.qtd_total}</div>
                     <div className="text-[10px] font-medium text-gray-500 uppercase">Expedidas</div>
                  </div>
                  {!isCompleto && (
                     <Progress value={progresso} className="w-16 h-2" />
                  )}
               </div>
            </div>
         </CardContent>
      </Card>
    );
  };

  return (
    <div className="container mx-auto p-4 space-y-8">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Expedição</h1>
          <p className="text-muted-foreground">Sincronização de Capas e Miolos</p>
        </div>
        <div className="flex bg-gray-100 p-1 rounded-lg">
          <button 
            onClick={() => setFilterTrilha('ALL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'ALL' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Todos
          </button>
          <button 
            onClick={() => setFilterTrilha('PRINCIPAL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'PRINCIPAL' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Prioridades
          </button>
          <button 
            onClick={() => setFilterTrilha('LATERAL')}
            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${filterTrilha === 'LATERAL' ? 'bg-white shadow-sm text-teal-600' : 'text-gray-500 hover:text-gray-900'}`}
          >
            Laterais
          </button>
        </div>
      </div>

      {/* MATCHES SECTION */}
      <section>
         <div className="flex items-center gap-2 mb-4">
            <CheckCircle2 className="h-6 w-6 text-green-600" />
            <h2 className="text-xl font-bold text-green-900">Prontos para Montagem ({matches.length})</h2>
         </div>
         {matches.length === 0 ? (
            <div className="bg-gray-50 border-2 border-dashed border-gray-200 rounded-xl p-8 text-center text-gray-400">
               Nenhum match completo no momento. Aguarde a produção.
            </div>
         ) : (
            <div className="space-y-4">
               {matches.map(item => <MatchCard key={item.item_id} item={item} />)}
            </div>
         )}
      </section>

      {/* CLOSING SECTION */}
      {closing.length > 0 && (
         <section>
            <div className="flex items-center gap-2 mb-4 mt-8">
               <Package className="h-5 w-5 text-blue-600" />
               <h2 className="text-lg font-bold text-blue-900">Em Fechamento ({closing.length})</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
               {closing.map(item => <ClosingCard key={item.item_id} item={item} />)}
            </div>
         </section>
      )}

      {/* PENDING SECTION */}
      <section>
         <div className="flex items-center gap-2 mb-4 mt-8">
            <Loader2 className="h-5 w-5 text-gray-400" />
            <h2 className="text-lg font-bold text-gray-600">Aguardando Peças ({pending.length})</h2>
         </div>
         <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pending.map(item => <PendingCard key={item.item_id} item={item} />)}
            {pending.length === 0 && matches.length > 0 && closing.length === 0 && (
               <div className="col-span-full text-center text-gray-400 py-8">
                  Tudo o que está na lista já pode ser montado!
               </div>
            )}
         </div>
      </section>
    </div>
  );
};

export default ExpedicaoDashboardPage;
