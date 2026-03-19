import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { 
  Package, 
  ArrowRight, 
  Calendar, 
  Clock,
  ExternalLink,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

/**
 * Card que exibe demandas vinculadas a um pedido
 */
export default function PedidoDemandaCard({ pedidoId, demandas = [], onRefresh }) {
  const navigate = useNavigate();

  const getStatusBadge = (status) => {
    const statusConfig = {
      'AGUARDANDO': { bg: 'bg-amber-500', text: 'Aguardando' },
      'EM_PRODUCAO': { bg: 'bg-blue-500', text: 'Em Produção' },
      'COLETA_PARCIAL': { bg: 'bg-purple-500', text: 'Coleta Parcial' },
      'COLETADO': { bg: 'bg-indigo-500', text: 'Coletado' },
      'CONCLUIDO': { bg: 'bg-green-500', text: 'Concluído' },
      'CANCELADO': { bg: 'bg-red-500', text: 'Cancelado' }
    };
    
    const config = statusConfig[status] || { bg: 'bg-gray-500', text: status };
    
    return (
      <Badge className={`${config.bg} text-white text-xs`}>
        {config.text}
      </Badge>
    );
  };

  const handleVerDemanda = (demandaId) => {
    navigate(`/producao/demanda/${demandaId}`);
  };

  const handleCriarDemanda = () => {
    navigate(`/consolidar?pedidos=${pedidoId}`);
  };

  if (!demandas || demandas.length === 0) {
    return (
      <Card className="border-amber-200 bg-amber-50/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2 text-amber-800">
            <AlertCircle className="w-5 h-5" />
            Demanda Vinculada
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <p className="text-sm text-amber-700">
              Este pedido ainda não está vinculado a nenhuma demanda de produção.
            </p>
            <Button 
              onClick={handleCriarDemanda}
              className="w-full bg-amber-600 hover:bg-amber-700"
            >
              <Package className="w-4 h-4 mr-2" />
              Criar Demanda
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Package className="w-5 h-5" />
          Demanda{demandas.length > 1 ? 's Vinculada' + 's' : ' Vinculada'} ({demandas.length})
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {demandas.map((demanda, index) => (
            <div 
              key={demanda.demanda_id || index}
              className="p-4 rounded-lg border bg-muted/30 space-y-3"
            >
              {/* Cabeçalho da Demanda */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <h4 className="font-semibold text-sm truncate">
                    {demanda.descricao || `Demanda #${demanda.demanda_id?.substring(0, 8)}`}
                  </h4>
                  <div className="flex items-center gap-2 mt-1">
                    {getStatusBadge(demanda.status)}
                    {demanda.is_flex && (
                      <Badge className="bg-amber-500 text-white text-xs">
                        FLEX
                      </Badge>
                    )}
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleVerDemanda(demanda.demanda_id)}
                  className="shrink-0"
                >
                  Ver
                  <ArrowRight className="w-3 h-3 ml-1" />
                </Button>
              </div>

              {/* Progresso */}
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Progresso</span>
                  <span className="font-medium">{demanda.progresso}%</span>
                </div>
                <Progress value={demanda.progresso} className="h-2" />
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{demanda.itens_finalizados} / {demanda.total_itens} itens finalizados</span>
                  <span>{demanda.qtd_pedidos_vinculados} {demanda.qtd_pedidos_vinculados === 1 ? 'pedido' : 'pedidos'}</span>
                </div>
              </div>

              {/* Informações Adicionais */}
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                {demanda.data_entrega && (
                  <div className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    <span>Entrega: {new Date(demanda.data_entrega).toLocaleDateString('pt-BR')}</span>
                  </div>
                )}
                {demanda.horario_coleta && (
                  <div className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    <span>Coleta: {demanda.horario_coleta}</span>
                  </div>
                )}
                {demanda.canal_venda?.nome && (
                  <div className="flex items-center gap-1">
                    <ExternalLink className="w-3 h-3" />
                    <span>{demanda.canal_venda.nome}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
