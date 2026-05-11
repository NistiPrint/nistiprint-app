import EditableCell from '@/components/EditableCell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
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
    ArrowUp,
    ArrowUpCircle,
    Bot,
    CheckCircle,
    CheckSquare,
    Edit,
    List,
    MoreVertical,
    PlayCircle,
    Printer,
    ShoppingCart,
    StickyNote,
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
  isLateral
}) => {
  const navigate = useNavigate();
  const { canEditField, canExecuteAction } = usePermissions();
  const [isExpanded, setIsExpanded] = useState(false);
  const [showPedidosOrigem, setShowPedidosOrigem] = useState(false);

  const diasRest = diasRestantes(demanda.data_entrega);
  const urgente = isUrgente(demanda.data_entrega, demanda.horario_coleta);
  const timeRemainingObj = calculateTimeRemaining(demanda.horario_coleta, demanda.data_entrega);
  
  const actionRequired = checkActionRequired(demanda, userSetor?.nome || userSetor);

  const priorityScore = demanda.manual_priority_score || 0;
  const modalidadeLogistica = demanda.modalidade_logistica || 'STANDARD';
  const classificacaoCliente = demanda.classificacao_cliente || 'B2C';
  const hasObservacoes = Boolean(demanda.observacoes && demanda.observacoes.trim());

  // Verifica se é entrega expressa (substitui o is_flex)
  const isExpress = modalidadeLogistica === 'EXPRESS';
  
  // Lógica de "Última Chance": Se o deadline operacional é o mesmo do final, não há backup
  const isLastChance = demanda.horario_coleta === demanda.deadline_final;
  
  const isEmergency = priorityScore >= 100 || isExpress || (isLastChance && urgente);
  const isNext = priorityScore >= 50 && priorityScore < 100;
  const showCriticalBadge = priorityScore >= 100 || (isLastChance && urgente);

  const totalItens = demanda.total_itens || demanda.total_quantidade || 1;
  // itens_prontos_para_retirar = unidades completas (capa + miolo) no buffer de prontos
  const itensProntosParaRetirar = demanda.itens_concluidos || 0;
  // itens_finalizados = itens que foram FINALIZADOS manualmente no dashboard (progresso real)
  const itensFinalizados = demanda.completed_quantidade || 0;
  // itens_em_fechamento = soma do menor valor entre exp. capas e exp. miolos (retirados pela expedição)
  const itensEmFechamento = demanda.itens_em_fechamento || 0;

  // Progresso total considera estritamente itens finalizados manualmente
  const percentualConcluido = (itensFinalizados / totalItens) * 100;

  const capasImpressas = demanda.capas_impressas_qtd || 0;
  const capasProduzidas = demanda.capas_produzidas_qtd || 0;
  const capasProntas = demanda.capas_prontas_retirada_qtd || 0;
  const miolosProntos = demanda.miolos_prontos_retirada_qtd || 0;

  // Lógica de Descompasso entre setores (Compara componentes produzidos)
  const temDescompasso = Math.abs(capasProduzidas - miolosProntos) > (totalItens * 0.2) && percentualConcluido < 100;

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
    { label: 'Capas Imp.', val: demanda.capas_impressas_qtd || 0, color: '#3b82f6', bgColor: 'bg-blue-500' },
    { label: 'Capas Prod.', val: demanda.capas_produzidas_qtd || 0, color: '#10b981', bgColor: 'bg-emerald-500' },
    { label: 'Capas Prontas', val: demanda.capas_prontas_retirada_qtd || 0, color: '#eab308', bgColor: 'bg-yellow-500' },
    { label: 'Miolos Prontos', val: demanda.miolos_prontos_retirada_qtd || 0, color: '#ec4899', bgColor: 'bg-pink-500' },
  ];

  const doneData = [
    { label: 'Capas impressas', val: capasImpressas, scope: totalItens, color: '#3b82f6', bgColor: 'bg-blue-500' },
    { label: 'Capas produzidas', val: capasProduzidas, scope: totalItens, color: '#10b981', bgColor: 'bg-emerald-500' },
    { label: 'Capas prontas', val: capasProntas, scope: totalItens, color: '#eab308', bgColor: 'bg-yellow-500' },
    { label: 'Miolos prontos', val: miolosProntos, scope: totalItens, color: '#ec4899', bgColor: 'bg-pink-500' },
    { label: 'Prontos para retirar', val: itensProntosParaRetirar, scope: totalItens, color: '#6b7280', bgColor: 'bg-gray-500' },
    { label: 'Sendo fechados (Exp)', val: itensEmFechamento, scope: totalItens, color: '#8b5cf6', bgColor: 'bg-violet-500' },
    { label: 'Finalizados (Manual)', val: itensFinalizados, scope: totalItens, color: '#22c55e', bgColor: 'bg-green-500' }
  ];

  const todoData = [
    { label: 'Capas a imprimir', val: Math.max(0, totalItens - capasImpressas), scope: totalItens, color: '#ef4444', bgColor: 'bg-red-500' },
    { label: 'Capas a finalizar', val: Math.max(0, capasImpressas - capasProduzidas), scope: totalItens, color: '#f97316', bgColor: 'bg-orange-500' },
    { label: 'Capas a casar', val: Math.max(0, capasProduzidas - capasProntas), scope: totalItens, color: '#fbbf24', bgColor: 'bg-yellow-400' },
    { label: 'Miolos a entregar', val: Math.max(0, totalItens - miolosProntos), scope: totalItens, color: '#ec4899', bgColor: 'bg-pink-500' },
    { label: 'Faltam retirar', val: Math.max(0, itensProntosParaRetirar - itensEmFechamento), scope: itensProntosParaRetirar, color: '#6b7280', bgColor: 'bg-gray-500' },
    { label: 'Faltam finalizar', val: Math.max(0, totalItens - itensFinalizados), scope: totalItens, color: '#22c55e', bgColor: 'bg-green-500' }
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
                {demanda.pedido_id && (
                  <div className="flex items-center gap-1.5 text-[11px]">
                    <ShoppingCart className="h-3 w-3 text-blue-500" />
                    <button 
                      onClick={(e) => { e.stopPropagation(); navigate(`/vendas/pedidos-unificados?searchTerm=${demanda.pedido_numero}`); }}
                      className="text-blue-600 hover:underline font-semibold"
                    >
                      Pedido: {demanda.pedido_numero}
                    </button>
                  </div>
                )}
              </div>
              
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline" className="text-[10px] px-1.5 h-5 border-gray-300 text-gray-600">{demanda.status}</Badge>
                {showCriticalBadge && <Badge className="bg-red-600 text-white border-none text-[10px] px-1.5 h-5">PRIORIDADE MAXIMA</Badge>}
                {isLastChance && urgente && <Badge className="bg-orange-600 text-white border-none text-[10px] px-1.5 h-5">ULTIMA CHANCE</Badge>}
                {urgente && <Badge variant="destructive" className="text-[10px] px-1.5 h-5">URGENTE</Badge>}
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
                {hasObservacoes && (
                  <Badge variant="outline" className="text-[10px] px-1.5 h-5 border-amber-200 text-amber-700 bg-amber-50 gap-1">
                    <StickyNote className="h-3 w-3" />
                    Obs.
                  </Badge>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1">
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
                <DropdownMenuItem onClick={(e) => { e.stopPropagation(); setShowPedidosOrigem(true); }}>
                  <List className="mr-2 h-4 w-4" /> Ver Pedidos Relacionados
                </DropdownMenuItem>
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
              <span className="text-[10px] font-bold text-gray-900">{Math.round(percentualConcluido)}% ({itensFinalizados}/{totalItens})</span>
            </div>
          </div>
          <Progress value={percentualConcluido} className="h-1.5" indicatorClassName={percentualConcluido === 100 ? 'bg-green-500' : ''} />
        </div>

        {/* Expanded Content */}
        {isExpanded && (
          <div className="px-4 pb-4 pt-2 border-t border-gray-50 bg-gray-50/50 animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
              <div className="md:col-span-8">
                {hasObservacoes && (
                  <div className="mb-4 rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <div className="mb-1 flex items-center gap-1.5 font-bold">
                      <StickyNote className="h-3.5 w-3.5" />
                      Observacoes
                    </div>
                    <p className="whitespace-pre-wrap leading-relaxed">{demanda.observacoes}</p>
                  </div>
                )}
                <div className="mb-4 flex flex-wrap gap-2 text-xs">
                  {demanda.origem_demanda && (
                    <Badge variant="outline" className="gap-1">
                      {demanda.origem_demanda === 'AUTOMATICA' ? <Bot className="h-3 w-3" /> : <Edit className="h-3 w-3" />}
                      {demanda.origem_demanda === 'AUTOMATICA' ? 'Automatica' : 'Manual'}
                    </Badge>
                  )}
                  {isLateral && (
                    <Badge variant="outline">Trilha lateral</Badge>
                  )}
                  {demanda.empresa_cliente_nome && (
                    <Badge variant="secondary">Empresa: {demanda.empresa_cliente_nome}</Badge>
                  )}
                  {demanda.empresa_responsavel_nome && (
                    <Badge variant="secondary">Contato: {demanda.empresa_responsavel_nome}</Badge>
                  )}
                </div>
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

      {/* Dialog for viewing related orders */}
      <Dialog open={showPedidosOrigem} onOpenChange={setShowPedidosOrigem}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Pedidos Relacionados - {demanda.nome}</DialogTitle>
          </DialogHeader>
          {demanda.pedidos_origem && demanda.pedidos_origem.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Código Pedido Externo</TableHead>
                  <TableHead>Número Pedido</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {demanda.pedidos_origem.map((pedido, idx) => (
                  <TableRow key={idx}>
                    <TableCell>{pedido.codigo_pedido_externo || '-'}</TableCell>
                    <TableCell>{pedido.numero_pedido || '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-center py-8 text-gray-500">
              Nenhum pedido relacionado encontrado.
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
});

export default DemandaCard;
