import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { CheckCircle2, ChevronRight, Package, Plus } from 'lucide-react';
import React, { useState } from 'react';

const ProductionHeroCard = ({ 
  item, 
  onUpdateProgress, 
  userSetor,
  isLateral = false 
}) => {
  const [addingQty, setAddingQty] = useState(null);

  if (!item) return null;

  // Determine colors based on line type
  const theme = isLateral ? {
    bg: 'bg-lateral-line-soft',
    border: 'border-lateral-line',
    text: 'text-lateral-line-strong',
    button: 'bg-lateral-line hover:bg-lateral-line-strong',
    badge: 'bg-lateral-line text-white',
    lightText: 'text-teal-600'
  } : {
    bg: 'bg-main-line-soft',
    border: 'border-main-line',
    text: 'text-main-line-strong',
    button: 'bg-main-line hover:bg-main-line-strong',
    badge: 'bg-main-line text-white',
    lightText: 'text-orange-600'
  };

  // Determine current progress based on sector
  let currentProgress = 0;
  let targetTotal = item.quantidade_total || 0;

  if (userSetor === 'Capas') {
    currentProgress = item.progresso_capas?.real_ficando_prontas || 0; // Or whatever field maps to "Done" for Capas
  } else if (userSetor === 'Miolos') {
    currentProgress = item.progresso_miolos?.prontos_retirada || 0;
  } else {
    // Default fallback
    currentProgress = 0;
  }
  
  // Correction: Use the fields we identified in PainelProducaoPage.jsx
  // Capas: capas_produzidas_qtd
  // Miolos: miolos_prontos_retirada_qtd
  if (userSetor === 'Capas') {
      currentProgress = item.capas_produzidas_qtd || item.progresso_capas?.real_ficando_prontas || 0;
  } else if (userSetor === 'Miolos') {
      currentProgress = item.miolos_prontos_retirada_qtd || item.progresso_miolos?.prontos_retirada || 0;
  }

  const remaining = Math.max(0, targetTotal - currentProgress);
  const percentage = Math.min(100, Math.round((currentProgress / targetTotal) * 100));

  const handleAdd = (qty) => {
    if (onUpdateProgress) {
      onUpdateProgress(item, qty);
    }
  };

  return (
    <Card className={`w-full overflow-hidden border-4 ${theme.border} shadow-xl`}>
      <div className={`${theme.bg} p-6 md:p-8 flex flex-col h-full justify-between min-h-[400px]`}>
        
        {/* Header Section */}
        <div className="flex justify-between items-start mb-6">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <Badge className={`${theme.badge} text-sm px-3 py-1 uppercase tracking-widest`}>
                {isLateral ? 'Oportunidade (Backlog)' : 'Prioridade Atual'}
              </Badge>
              <span className="text-gray-500 font-mono font-bold">#{item.id}</span>
            </div>
            <h1 className={`text-4xl md:text-5xl font-black ${theme.text} leading-tight mb-2`}>
              {item.item_descricao}
            </h1>
            {item.miolo_name && (
               <h2 className={`text-xl md:text-2xl font-bold ${theme.lightText}`}>
                 Miolo: {item.miolo_name}
               </h2>
            )}
            <div className="mt-2 text-gray-500 font-medium">
               Demanda: {item.demanda_nome}
            </div>
          </div>
          
          <div className="text-right">
             <div className="text-6xl md:text-8xl font-black text-gray-900 tracking-tighter">
                {remaining}
             </div>
             <div className="text-sm font-bold text-gray-400 uppercase tracking-widest">Restantes</div>
          </div>
        </div>

        {/* Progress Section */}
        <div className="space-y-4 mb-8">
           <div className="flex justify-between items-end">
              <span className="text-2xl font-bold text-gray-700">Progresso</span>
              <span className="text-2xl font-bold text-gray-900">{currentProgress} / {targetTotal}</span>
           </div>
           <div className="h-6 w-full bg-white rounded-full border border-gray-200 overflow-hidden">
              <div 
                className={`h-full ${theme.button} transition-all duration-500 ease-out`} 
                style={{ width: `${percentage}%` }}
              />
           </div>
        </div>

        {/* Action Buttons (KDS Style) */}
        <div className="grid grid-cols-3 gap-4 h-32">
           <Button 
             className="h-full text-2xl font-bold bg-white text-gray-900 border-2 border-gray-200 hover:bg-gray-50 hover:border-gray-300"
             onClick={() => handleAdd(1)}
           >
             <Plus className="w-6 h-6 mr-2" /> 1
           </Button>
           
           <Button 
             className="h-full text-2xl font-bold bg-white text-gray-900 border-2 border-gray-200 hover:bg-gray-50 hover:border-gray-300"
             onClick={() => handleAdd(10)}
           >
             <Plus className="w-6 h-6 mr-2" /> 10
           </Button>

           <Button 
             className={`h-full text-2xl font-bold ${theme.button} text-white shadow-lg`}
             onClick={() => handleAdd(remaining)}
           >
             <CheckCircle2 className="w-8 h-8 mr-2" /> 
             Tudo
           </Button>
        </div>

      </div>
    </Card>
  );
};

export default ProductionHeroCard;
