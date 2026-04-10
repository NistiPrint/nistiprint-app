import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import {
  AlertTriangle,
  Clock,
  Edit,
  Eye,
  MoreVertical,
  PlayCircle,
  ShoppingCart,
  Trash2,
  User
} from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * Card de Rascunho de Demanda Automática.
 * 
 * Mostra o estado do rascunho:
 * - Limpo (sem edição)
 * - Editado (✏️)
 * - Modificado (⚠️ +N)
 */
export default function RascunhoCard({
  rascunho,
  onPublicar,
  onEditar,
  onDeletar,
  onVerNovos,
}) {
  const navigate = useNavigate();
  const [isExpanded, setIsExpanded] = useState(false);

  const {
    id,
    nome,
    descricao,
    quantidade,
    data_entrega,
    horario_coleta,
    modalidade_logistica,
    canal_nome,
    canal_color,
    canal_flex,
    produto_nome,
    total_pedidos,
    pedidos_apos_edicao_qtd,
    editado_pelo_usuario,
    editado_em,
    rascunho_expira_em,
    created_at,
  } = rascunho;

  // Calcular tempo restante para expiração
  const tempoRestante = (() => {
    if (!rascunho_expira_em) return null;
    const expira = new Date(rascunho_expira_em);
    const agora = new Date();
    const diff = expira - agora;

    if (diff <= 0) return { texto: 'Expirado', cor: 'text-red-600', urgente: true };
    
    const horas = Math.floor(diff / (1000 * 60 * 60));
    const minutos = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    
    if (horas === 0) {
      return { texto: `${minutos} min`, cor: 'text-red-600', urgente: true };
    } else if (horas < 2) {
      return { texto: `${horas}h ${minutos}min`, cor: 'text-orange-600', urgente: true };
    } else {
      return { texto: `${horas}h ${minutos}min`, cor: 'text-green-600', urgente: false };
    }
  })();

  // Determinar estado do rascunho
  const estadoRascunho = (() => {
    if (pedidos_apos_edicao_qtd > 0) return 'modificado';
    if (editado_pelo_usuario) return 'editado';
    return 'limpo';
  })();

  // Cor do badge baseado no estado
  const estadoConfig = {
    limpo: { badge: null, icone: null },
    editado: { badge: '✏️ Editado', icone: Edit },
    modificado: { badge: `⚠️ +${pedidos_apos_edicao_qtd}`, icone: AlertTriangle },
  };

  const estadoAtual = estadoConfig[estadoRascunho];

  // Verificar se cor do canal é clara
  const isLightColor = (color) => {
    if (!color) return false;
    const hex = color.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.6;
  };

  const isLightBackground = isLightColor(canal_color);

  // Formatar data de criação
  const dataCriacao = created_at ? new Date(created_at).toLocaleDateString('pt-BR') : '';
  const horaCriacao = created_at ? new Date(created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';

  return (
    <Card className={cn(
      "relative shadow-sm hover:shadow-md transition-all cursor-pointer border-l-4",
      estadoRascunho === 'modificado' && "border-l-red-500 ring-1 ring-red-200",
      estadoRascunho === 'editado' && "border-l-yellow-500",
      estadoRascunho === 'limpo' && "border-l-blue-500"
    )}>
      {/* Canal Badge */}
      <div
        className={cn(
          "absolute top-0 left-1/2 transform -translate-x-1/2 px-3 py-0.5 rounded-b-md text-[10px] font-bold uppercase tracking-wider shadow-sm z-10",
          isLightBackground ? 'text-gray-900' : 'text-white'
        )}
        style={{ backgroundColor: canal_color }}
      >
        {canal_nome}
      </div>

      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-4">
          {/* Esquerda: Informações principais */}
          <div className="flex-1 min-w-0">
            {/* Título */}
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-lg font-bold text-gray-900 truncate">
                {nome || descricao || 'Rascunho'}
              </h3>
              <span className="text-xs text-gray-400 font-mono">#{id.toString().slice(-4)}</span>
            </div>

            {/* Estado do rascunho */}
            <div className="flex flex-wrap items-center gap-2 mb-2">
              {estadoAtual.icone && (
                <Badge
                  variant={estadoRascunho === 'modificado' ? 'destructive' : 'secondary'}
                  className={cn(
                    "text-[10px] px-1.5 h-5",
                    estadoRascunho === 'modificado' && "animate-pulse"
                  )}
                >
                  {estadoAtual.badge}
                </Badge>
              )}

              {modalidade_logistica && modalidade_logistica !== 'STANDARD' && (
                <Badge className="bg-blue-100 text-blue-800 border-none text-[10px] px-1.5 h-5">
                  {modalidade_logistica}
                </Badge>
              )}

              {canal_flex && (
                <Badge className="bg-purple-600 text-white border-none text-[10px] px-1.5 h-5">
                  FLEX
                </Badge>
              )}

              <Badge variant="outline" className="text-[10px] px-1.5 h-5 border-gray-300 text-gray-600">
                RASCUNHO
              </Badge>
            </div>

            {/* Metadados */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
              <div className="flex items-center gap-1">
                <ShoppingCart className="h-3 w-3" />
                <span>{total_pedidos} pedidos</span>
              </div>
              <div className="flex items-center gap-1">
                <span className="font-semibold">{quantidade || 0} unidades</span>
              </div>
              {horario_coleta && (
                <div className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  <span>Coleta: {horario_coleta}</span>
                </div>
              )}
              {data_entrega && (
                <div className="flex items-center gap-1">
                  <span>Entrega: {new Date(data_entrega).toLocaleDateString('pt-BR')}</span>
                </div>
              )}
            </div>
          </div>

          {/* Direita: Ações e Tempo */}
          <div className="flex items-center gap-2">
            {/* Tempo restante */}
            <div className="text-right">
              <div className={cn("text-sm font-bold", tempoRestante?.cor)}>
                {tempoRestante?.texto || '--'}
              </div>
              <div className="text-[10px] text-gray-400">
                {tempoRestante?.urgente ? 'Expira em breve' : 'Janela aberta'}
              </div>
            </div>

            {/* Menu Dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => navigate(`/consolidar/rascunhos/${id}/editar`)}>
                  <Edit className="mr-2 h-4 w-4" /> Editar
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onVerNovos(id)} disabled={pedidos_apos_edicao_qtd === 0}>
                  <Eye className="mr-2 h-4 w-4" /> Ver Novos Pedidos
                </DropdownMenuItem>
                <div className="h-px bg-gray-200 my-1" />
                <DropdownMenuItem onClick={() => onPublicar(id)} className="text-green-600 font-semibold">
                  <PlayCircle className="mr-2 h-4 w-4" /> Publicar Demanda
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onDeletar(id)} className="text-red-600">
                  <Trash2 className="mr-2 h-4 w-4" /> Deletar Rascunho
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Botão Expandir */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0"
              onClick={(e) => {
                e.stopPropagation();
                setIsExpanded(!isExpanded);
              }}
            >
              {isExpanded ? (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                </svg>
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              )}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Informações adicionais (expandido) */}
        {isExpanded && (
          <div className="border-t pt-4 mt-2 space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
            {/* Produto */}
            {produto_nome && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-500">Produto:</span>
                <span className="font-semibold text-gray-900">{produto_nome}</span>
              </div>
            )}

            {/* Edição */}
            {editado_pelo_usuario && editado_em && (
              <div className="flex items-center gap-2 text-sm">
                <User className="h-4 w-4 text-gray-400" />
                <span className="text-gray-500">Editado:</span>
                <span className="font-medium">
                  {new Date(editado_em).toLocaleDateString('pt-BR')} às {new Date(editado_em).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            )}

            {/* Expiração */}
            {rascunho_expira_em && (
              <div className="flex items-center gap-2 text-sm">
                <Clock className={cn("h-4 w-4", tempoRestante?.urgente ? 'text-red-500' : 'text-green-500')} />
                <span className="text-gray-500">Expira em:</span>
                <span className={cn("font-semibold", tempoRestante?.cor)}>
                  {new Date(rascunho_expira_em).toLocaleDateString('pt-BR')} às {new Date(rascunho_expira_em).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            )}

            {/* Criação */}
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <span>Criado em {dataCriacao} às {horaCriacao}</span>
            </div>

            {/* Ações rápidas */}
            <div className="flex gap-2 pt-2">
              <Button
                size="sm"
                onClick={() => onPublicar(id)}
                className="flex-1 bg-green-600 hover:bg-green-700"
              >
                <PlayCircle className="mr-2 h-4 w-4" /> Publicar
              </Button>
              {pedidos_apos_edicao_qtd > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onVerNovos(id)}
                  className="flex-1 border-orange-300 text-orange-700 hover:bg-orange-50"
                >
                  <AlertTriangle className="mr-2 h-4 w-4" /> Ver {pedidos_apos_edicao_qtd} Novos
                </Button>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
