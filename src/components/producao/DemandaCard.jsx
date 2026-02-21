import EditableCell from '@/components/EditableCell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { usePermissions } from '@/contexts/PermissionsContext';
import { calculateTimeRemaining, diasRestantes, isUrgente } from '@/lib/demandaUtils';
import { checkActionRequired } from '@/lib/notificationLogic';
import {
  AlertTriangle,
  ArrowRight,
  ArrowUp,
  ArrowUpCircle,
  CheckCircle,
  CheckSquare,
  Edit,
  MoreVertical,
  PlayCircle,
  Printer,
  Trash2,
  Truck
} from 'lucide-react';
import React from 'react';
import { useNavigate } from 'react-router-dom';

import { Checkbox } from '@/components/ui/checkbox';
import { Progress } from '@/components/ui/progress';
import {
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { useState } from 'react';

const DemandaCard = React.memo(({
  demanda,
  userSetor,
  viewMode,
  handleFieldUpdate,
  handleFinalizeDemand,
  handleCollectDemand,
  handleDeleteDemand,
  handlePublishDemand,
  handlePrintDemand,
  isSelected,
  onSelect,
  isMainLine,
  isLateral
}) => {
  const navigate = useNavigate();
  const { canEditField, canExecuteAction } = usePermissions();
  const [isExpanded, setIsExpanded] = useState(false);

  const diasRest = diasRestantes(demanda.data_entrega);
  const urgente = isUrgente(demanda.data_entrega, demanda.horario_coleta);
  const timeRemainingObj = calculateTimeRemaining(demanda.horario_coleta, demanda.data_entrega);
  const deadlineFinalObj = calculateTimeRemaining(demanda.deadline_final, demanda.data_entrega);
  
  const actionRequired = checkActionRequired(demanda, userSetor?.nome || userSetor);

  const priorityScore = demanda.manual_priority_score || 0;
  const isFlex = demanda.is_flex === true;
  const modalidadeLogistica = demanda.modalidade_logistica || 'STANDARD';
  const classificacaoCliente = demanda.classificacao_cliente || 'B2C';

  // Verifica se é entrega expressa (substitui o is_flex)
  const isExpress = modalidadeLogistica === 'EXPRESS';
  
  // Lógica de "Última Chance": Se o deadline operacional é o mesmo do final, não há backup
  const isLastChance = demanda.horario_coleta === demanda.deadline_final;
  
  const isEmergency = priorityScore >= 100 || isExpress || (isLastChance && urgente);
  const isNext = priorityScore >= 50 && priorityScore < 100;

  const totalItens = demanda.total_itens || demanda.total_quantidade || 1;
  const itensConcluidos = demanda.itens_concluidos || 0;
  const percentualConcluido = (itensConcluidos / totalItens) * 100;

  const isStuck = demanda.is_stuck === true;

  // Lógica de Descompasso entre setores
  const capasProntas = demanda.capas_produzidas_qtd || 0;
  const miolosProntos = demanda.miolos_produzidos_qtd || 0;
  const temDescompasso = Math.abs(capasProntas - miolosProntos) > (totalItens * 0.2) && percentualConcluido < 100;

  const canalColor = demanda.canal_venda_color || '#6b7280';

  const isLightColor = (color) => {
    if (!color) return false;
    const hex = color.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.6;
  };

  const isLightBackground = isLightColor(canalColor);

  const borderColor = demanda.canal_venda_color || (
    isEmergency ? '#dc2626' :
    isNext ? '#f97316' :
    actionRequired ? '#eab308' :
    '#d1d5db'
  );

  const setoresData = [
    { label: 'Capas impressas', val: demanda.capas_impressas_qtd || 0, color: '#3b82f6', bgColor: 'bg-blue-500' },
    { label: 'Capas finalizadas', val: demanda.capas_produzidas_qtd || demanda.capas_prontas_retirada_qtd || 0, color: '#eab308', bgColor: 'bg-yellow-500' },
    { label: 'Miolos entregues', val: demanda.miolos_produzidos_qtd || demanda.miolos_prontos_retirada_qtd || 0, color: '#ec4899', bgColor: 'bg-pink-500' },
    { label: 'Itens completos retirados', val: demanda.completed_quantidade || 0, color: '#6b7280', bgColor: 'bg-gray-500' }
  ];

  const capasImpressas = demanda.capas_impressas_qtd || 0;
  const capasFinalizadas = demanda.capas_produzidas_qtd || demanda.capas_prontas_retirada_qtd || 0;
  const miolosEntregues = demanda.miolos_produzidos_qtd || demanda.miolos_prontos_retirada_qtd || 0;
  const itensProntos = demanda.itens_concluidos || 0;
  const itensRetirados = demanda.completed_quantidade || 0;

  const doneData = [
    { label: 'Capas impressas', val: capasImpressas, scope: totalItens, color: '#3b82f6', bgColor: 'bg-blue-500' },
    { label: 'Capas finalizadas', val: capasFinalizadas, scope: totalItens, color: '#eab308', bgColor: 'bg-yellow-500' },
    { label: 'Miolos entregues', val: miolosEntregues, scope: totalItens, color: '#ec4899', bgColor: 'bg-pink-500' },
    { label: 'Itens fechados', val: itensRetirados, scope: totalItens, color: '#6b7280', bgColor: 'bg-gray-500' }
  ];

  const todoData = [
    { label: 'Capas a imprimir', val: Math.max(0, totalItens - capasImpressas), scope: totalItens, color: '#ef4444', bgColor: 'bg-red-500' },
    { label: 'Capas a finalizar', val: Math.max(0, capasImpressas - capasFinalizadas), scope: capasImpressas, color: '#f97316', bgColor: 'bg-orange-500' },
    { label: 'Miolos a entregar', val: Math.max(0, totalItens - miolosEntregues), scope: totalItens, color: '#ec4899', bgColor: 'bg-pink-500' },
    { label: 'Itens disponíveis pra retirar', val: Math.max(0, itensProntos - itensRetirados), scope: itensProntos, color: '#6b7280', bgColor: 'bg-gray-500' }
  ];

  const progressData = viewMode === 'done' ? doneData : todoData;

  const DonutChart = ({ size = 120, strokeWidth = 16 }) => {
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const center = size / 2;
    let currentAngle = -90;

    return (
      <div className="relative flex items-center justify-center">
        <svg width={size} height={size}>
          <circle cx={center} cy={center} r={radius} fill="none" stroke="#f3f4f6" strokeWidth={strokeWidth} />
          {setoresData.map((setor, idx) => {
            const percentage = (setor.val || 0) / totalItens;
            const segmentLength = circumference * percentage;
            const dashArray = `${segmentLength} ${circumference}`;
            const rotation = currentAngle;
            currentAngle += percentage * 360;
            return (
              <circle
                key={idx} cx={center} cy={center} r={radius} fill="none" stroke={setor.color}
                strokeWidth={strokeWidth} strokeDasharray={dashArray} strokeDashoffset={0}
                transform={`rotate(${rotation} ${center} ${center})`}
                className="transition-all duration-700"
                style={{ strokeLinecap: 'round' }}
              />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className="text-2xl font-black text-gray-900">{Math.round(percentualConcluido)}%</div>
        </div>
      </div>
    );
  };

  const ProgressBars = () => (
    <div className="space-y-3 w-full">
      {progressData.map((step, i) => {
        const currentVal = step.val || 0;
        const totalScope = step.scope || 1;
        const percentage = totalScope > 0 ? Math.min(Math.round((currentVal / totalScope) * 100), 100) : 0;
        return (
          <div key={i}>
            <div className="flex items-center justify-between text-[11px] mb-1 px-1">
              <div className="flex items-center gap-2">
                <span className="font-bold text-gray-700">{step.label}</span>
                <span className="text-gray-400">({currentVal})</span>
              </div>
              <span className="font-bold text-gray-900">{percentage}%</span>
            </div>
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden border border-gray-50">
              <div className={`h-full ${step.bgColor} transition-all duration-700 ease-out`} style={{ width: `${percentage}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );

  const handleCardClick = (e) => {
    if (e.target.closest('button') || e.target.closest('[data-editable]') || e.target.closest('a') || e.target.closest('input[type="checkbox"]')) {
      return;
    }
    navigate(`/producao/demanda/${demanda.id}/dashboard`);
  };

  return (
    <Card
      onClick={handleCardClick}
      className={`relative shadow-sm hover:shadow-md transition-all cursor-pointer border-l-4 ${isSelected ? 'ring-2 ring-primary' : ''}`}
      style={{ borderLeftColor: borderColor }}
    >
      {/* Canal Badge / Header */}
      <div
        className={`absolute top-0 left-1/2 transform -translate-x-1/2 px-3 py-0.5 rounded-b-md text-[10px] font-bold uppercase tracking-wider shadow-sm z-10 ${
          isLightBackground ? 'text-gray-900' : 'text-white'
        }`}
        style={{ backgroundColor: canalColor }}
      >
        {demanda.canal_venda_plataforma}
      </div>

      <div className="flex flex-col">
        {/* Top Row: Title, Selection, Actions */}
        <div className="flex items-start justify-between p-4 pb-2">
          <div className="flex items-start gap-3 flex-1">
            <div onClick={(e) => e.stopPropagation()} className="pt-1">
              <Checkbox checked={isSelected} onCheckedChange={() => onSelect(demanda.id)} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-lg font-bold text-gray-900 truncate" data-editable>
                  <EditableCell
                    value={demanda.nome}
                    onSave={newValue => handleFieldUpdate(demanda.id, 'nome', newValue)}
                    isEditable={canEditField(userSetor, 'nome')}
                    type="text"
                  />
                </h3>
                <span className="text-xs text-gray-400 font-mono">#{demanda.id.toString().slice(-4)}</span>
              </div>

              {/* Links para Cadastro */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2">
                {demanda.produto_id && (
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <span className="text-gray-400 font-medium">Produto:</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); navigate(`/produtos/${demanda.produto_id}/editar`); }}
                      className="text-blue-600 hover:underline font-semibold truncate max-w-[150px]"
                    >
                      {demanda.produto_nome || 'Ver Cadastro'}
                    </button>
                  </div>
                )}
              </div>
              
              <div className="flex flex-wrap gap-1.5">
                {isExpress && <Badge className="bg-purple-600 text-white border-none text-[10px] px-1.5 h-5">EXPRESS</Badge>}
                {isEmergency && <Badge className="bg-red-600 text-white border-none animate-pulse text-[10px] px-1.5 h-5">PRIORIDADE MÁXIMA</Badge>}
                {isLastChance && urgente && <Badge className="bg-orange-600 text-white border-none text-[10px] px-1.5 h-5">⚠️ ÚLTIMA CHANCE</Badge>}
                {urgente && <Badge variant="destructive" className="text-[10px] px-1.5 h-5">URGENTE</Badge>}
                {isLateral && (() => {
                  const tipo = (demanda.tipo_demanda || '').toUpperCase();
                  const modalidade = (demanda.modalidade_logistica || '').toUpperCase();
                  return (
                    tipo === 'B2B' || 
                    tipo === 'EMPRESAS' ||
                    modalidade === 'FULFILLMENT' || 
                    tipo === 'ESTOQUE_INTERNO' || 
                    tipo === 'INTERNO' ||
                    diasRest > 3
                  );
                })() && <Badge className="bg-teal-600 text-white border-none text-[10px] px-1.5 h-5">LATERAL</Badge>}
                {isStuck && <Badge className="bg-amber-500 text-white border-none animate-pulse text-[10px] px-1.5 h-5">⚠️ TRAVADO</Badge>}
                {modalidadeLogistica && modalidadeLogistica !== 'STANDARD' && (
                  <Badge className="bg-blue-100 text-blue-800 border-none text-[10px] px-1.5 h-5">
                    {modalidadeLogistica === 'EXPRESS' ? 'EXPRESS' :
                     modalidadeLogistica === 'FULFILLMENT' ? 'FULFILLMENT' :
                     modalidadeLogistica === 'RETIRADA' ? 'RETIRADA' : modalidadeLogistica}
                  </Badge>
                )}
                {classificacaoCliente && classificacaoCliente !== 'B2C' && (
                  <Badge className="bg-green-100 text-green-800 border-none text-[10px] px-1.5 h-5">
                    {classificacaoCliente === 'B2B' ? 'B2B' :
                     classificacaoCliente === 'INTERNO' ? 'INTERNO' : classificacaoCliente}
                  </Badge>
                )}
                <Badge variant="outline" className="text-[10px] px-1.5 h-5 border-gray-300 text-gray-600">{demanda.status}</Badge>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1">
             {isStuck && isMainLine && (
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="hidden md:flex items-center gap-1 text-amber-600 hover:text-amber-700 hover:bg-amber-50 text-[10px] font-bold"
                  onClick={(e) => {
                    e.stopPropagation();
                    document.getElementById('side-tracks-section')?.scrollIntoView({ behavior: 'smooth' });
                  }}
                >
                  Ver Encaixes <ArrowRight className="h-3 w-3" />
                </Button>
             )}
             <div className="text-right mr-2 hidden sm:block">
                <div className={`text-xs font-bold ${timeRemainingObj.color}`}>
                  {timeRemainingObj.text || (diasRest > 0 ? `${diasRest}d` : 'Vencido')}
                </div>
                {diasRest === 0 && (
                  <div className="text-[10px] text-gray-400">
                    Finalizar até: {demanda.horario_coleta}
                    {!isLastChance && (
                      <span className="block text-orange-600 font-bold">
                        Crítico: {demanda.deadline_final}
                      </span>
                    )}
                  </div>
                )}
             </div>

            <DropdownMenu>
              <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {demanda.status !== 'Rascunho' && (
                  <>
                    <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleFieldUpdate(demanda.id, 'manual_priority_score', 100); }} className="text-red-600">
                      <ArrowUpCircle className="w-4 h-4 mr-2" /> Prioridade Máxima
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleFieldUpdate(demanda.id, 'manual_priority_score', 50); }} className="text-orange-600">
                      <ArrowUp className="w-4 h-4 mr-2" /> Definir como Próxima
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleFieldUpdate(demanda.id, 'manual_priority_score', 0); }}>
                      <CheckSquare className="w-4 h-4 mr-2" /> Remover Prioridade
                    </DropdownMenuItem>
                    <div className="h-px bg-gray-200 my-1" />
                  </>
                )}
                <DropdownMenuItem onClick={(e) => { e.stopPropagation(); navigate(`/producao/demanda/${demanda.id}/dashboard`); }}>
                  <PlayCircle className="mr-2 h-4 w-4" /> Abrir Dashboard
                </DropdownMenuItem>
                {canExecuteAction(userSetor, 'delete_demand') && (
                  <DropdownMenuItem onClick={(e) => { e.stopPropagation(); navigate(`/producao/demanda/${demanda.id}/editar`); }}>
                    <Edit className="mr-2 h-4 w-4" /> Editar
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handlePrintDemand(demanda.id); }}>
                    <Printer className="mr-2 h-4 w-4" /> Imprimir Tudo
                </DropdownMenuItem>
                {demanda.status === 'Rascunho' && (
                  <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handlePublishDemand(demanda.id); }} className="text-green-600">
                    <PlayCircle className="mr-2 h-4 w-4" /> Publicar
                  </DropdownMenuItem>
                )}
                {canExecuteAction(userSetor, 'finalize_item') && (
                  <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleFinalizeDemand(demanda.id); }}>
                    <CheckCircle className="mr-2 h-4 w-4" /> Finalizar
                  </DropdownMenuItem>
                )}
                {canExecuteAction(userSetor, 'collect_demand') && (
                  <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleCollectDemand(demanda.id); }}>
                    <Truck className="mr-2 h-4 w-4" /> Coletar
                  </DropdownMenuItem>
                )}
                {canExecuteAction(userSetor, 'delete_demand') && (
                  <DropdownMenuItem onClick={(e) => { e.stopPropagation(); handleDeleteDemand(demanda.id); }} className="text-red-600">
                    <Trash2 className="mr-2 h-4 w-4" /> Deletar
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}>
              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Linear Progress (Always Visible) */}
        <div className="px-4 pb-4">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-bold text-gray-500 uppercase">Progresso Total</span>
            <div className="flex items-center gap-3">
              {temDescompasso && (
                <Badge variant="outline" className="text-[10px] font-bold text-amber-600 border-amber-200 bg-amber-50 animate-pulse">
                  <AlertTriangle className="h-3 w-3 mr-1" /> DESCOMPASSO SETORES
                </Badge>
              )}
              {isLateral && demanda.readiness_score > 0 && (
                <span className="text-[10px] font-bold text-teal-600 bg-teal-50 px-1.5 py-0.5 rounded">
                  PRONTIDÃO: {demanda.readiness_score}%
                </span>
              )}
              <span className="text-[10px] font-bold text-gray-900">{Math.round(percentualConcluido)}% ({itensConcluidos}/{totalItens})</span>
            </div>
          </div>
          <Progress value={percentualConcluido} className="h-1.5" indicatorClassName={percentualConcluido === 100 ? 'bg-green-500' : ''} />
        </div>

        {/* Expanded Content */}
        {isExpanded && (
          <div className="px-4 pb-4 pt-2 border-t border-gray-50 bg-gray-50/50 animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
              <div className="md:col-span-8">
                <ProgressBars />
              </div>
              <div className="md:col-span-4 flex flex-col items-center justify-center border-l border-gray-100 pl-4">
                <DonutChart size={100} strokeWidth={14} />
                <div className="mt-2 text-center">
                   {demanda.tipo_demanda && (
                    <Badge variant="secondary" className="text-[10px] mb-1">
                      {demanda.tipo_demanda_label || demanda.tipo_demanda}
                    </Badge>
                  )}
                  <div className="text-[10px] text-gray-500">Criada em {new Date(demanda.data_criacao).toLocaleDateString()}</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
});

export default DemandaCard;