import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { 
  Clock, 
  Package, 
  CheckCircle2, 
  XCircle,
  Truck,
  AlertCircle,
  Calendar
} from 'lucide-react';

/**
 * Timeline de eventos do pedido
 */
export default function PedidoTimeline({ eventos }) {
  const getEventIcon = (tipoEvento) => {
    const icons = {
      ORDER_CREATED: <Package className="w-4 h-4" />,
      STATUS_CHANGED: <Clock className="w-4 h-4" />,
      ORDER_CANCELLED: <XCircle className="w-4 h-4" />,
      ORDER_PAID: <CheckCircle2 className="w-4 h-4" />,
      ORDER_SHIPPED: <Truck className="w-4 h-4" />,
      ORDER_DELIVERED: <CheckCircle2 className="w-4 h-4" />
    };
    return icons[tipoEvento] || <AlertCircle className="w-4 h-4" />;
  };

  const getEventColor = (tipoEvento) => {
    const colors = {
      ORDER_CREATED: 'text-blue-600',
      STATUS_CHANGED: 'text-amber-600',
      ORDER_CANCELLED: 'text-red-600',
      ORDER_PAID: 'text-green-600',
      ORDER_SHIPPED: 'text-purple-600',
      ORDER_DELIVERED: 'text-gray-600'
    };
    return colors[tipoEvento] || 'text-gray-600';
  };

  const formatarData = (dataISO) => {
    if (!dataISO) return '-';
    const data = new Date(dataISO);
    return data.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (!eventos || eventos.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Timeline de Eventos
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-center py-8">
            Nenhum evento registrado
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Calendar className="w-5 h-5" />
          Timeline de Eventos
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[400px] pr-4">
          <div className="space-y-4">
            {eventos.map((evento, index) => (
              <div key={evento.id || index} className="flex gap-3">
                {/* Linha do tempo */}
                <div className="flex flex-col items-center">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 bg-background ${getEventColor(evento.tipo_evento)}`}>
                    {getEventIcon(evento.tipo_evento)}
                  </div>
                  {index < eventos.length - 1 && (
                    <div className="w-0.5 h-full bg-border mt-2" />
                  )}
                </div>

                {/* Conteúdo do evento */}
                <div className="flex-1 pb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-sm">
                      {evento.descricao || evento.tipo_evento}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatarData(evento.created_at)}
                    </span>
                  </div>
                  
                  {evento.status_de && evento.status_para && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                      <span>De: <Badge variant="outline" className="text-xs">{evento.status_de}</Badge></span>
                      <span>→</span>
                      <span>Para: <Badge variant="outline" className="text-xs">{evento.status_para}</Badge></span>
                    </div>
                  )}
                  
                  {evento.metadata && (
                    <div className="text-xs text-muted-foreground mt-1">
                      {typeof evento.metadata === 'string' 
                        ? evento.metadata 
                        : JSON.stringify(evento.metadata)
                      }
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
