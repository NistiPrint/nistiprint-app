import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { 
  Calendar, 
  Package, 
  CheckCircle2, 
  XCircle,
  Truck,
  AlertCircle,
  Clock,
  TrendingUp,
  ClipboardCheck
} from 'lucide-react';

/**
 * Timeline unificada de eventos de uma demanda
 * Combina eventos da demanda + eventos dos pedidos vinculados
 */
export default function DemandaTimeline({ demandaId }) {
  const [timeline, setTimeline] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    carregarTimeline();
  }, [demandaId]);

  async function carregarTimeline() {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/demandas/${demandaId}/timeline`);
      const data = await response.json();
      
      if (data.success) {
        setTimeline(data.data.timeline || []);
      } else {
        console.error('Erro ao carregar timeline:', data.message);
      }
    } catch (error) {
      console.error('Erro de conexão:', error);
    } finally {
      setLoading(false);
    }
  }

  const getEventIcon = (tipoEvento, tipo) => {
    if (tipo === 'demanda') {
      const icons = {
        'DEMANDA_CREATED': <Package className="w-4 h-4" />,
        'DEMANDA_COMPLETED': <ClipboardCheck className="w-4 h-4" />,
        'DEMANDA_CANCELLED': <XCircle className="w-4 h-4" />
      };
      return icons[tipoEvento] || <Package className="w-4 h-4" />;
    }
    
    // Eventos de pedido
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

  const getEventColor = (tipoEvento, tipo) => {
    if (tipo === 'demanda') {
      return 'text-blue-600';
    }
    
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

  const getEventBadge = (tipo) => {
    if (tipo === 'demanda') {
      return (
        <Badge className="bg-blue-100 text-blue-800 border-blue-200 text-xs">
          <Package className="w-3 h-3 mr-1" />
          Demanda
        </Badge>
      );
    }
    return (
      <Badge className="bg-purple-100 text-purple-800 border-purple-200 text-xs">
        <Package className="w-3 h-3 mr-1" />
        Pedido
      </Badge>
    );
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

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Timeline de Eventos
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-12">
            <Clock className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (timeline.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Timeline de Eventos
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-12 text-muted-foreground">
            <AlertCircle className="w-12 h-12 mx-auto mb-4" />
            <p>Nenhum evento registrado</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Timeline de Eventos
          </div>
          <Badge variant="secondary" className="text-xs">
            {timeline.length} {timeline.length === 1 ? 'evento' : 'eventos'}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[500px] pr-4">
          <div className="space-y-4">
            {timeline.map((evento, index) => (
              <div key={evento.id} className="flex gap-3">
                {/* Linha do tempo */}
                <div className="flex flex-col items-center">
                  <div className={`w-9 h-9 rounded-full flex items-center justify-center border-2 bg-background ${getEventColor(evento.tipo_evento, evento.tipo)}`}>
                    {getEventIcon(evento.tipo_evento, evento.tipo)}
                  </div>
                  {index < timeline.length - 1 && (
                    <div className="w-0.5 h-full bg-border mt-2" />
                  )}
                </div>

                {/* Conteúdo do evento */}
                <div className="flex-1 pb-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      {getEventBadge(evento.tipo)}
                      <span className="font-medium text-sm">
                        {evento.descricao || evento.tipo_evento}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap ml-2">
                      {formatarData(evento.created_at)}
                    </span>
                  </div>
                  
                  {/* Mudança de status */}
                  {evento.status_de && evento.status_para && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-2 bg-muted/50 rounded-md p-2">
                      <span>Status:</span>
                      <Badge variant="outline" className="text-xs">{evento.status_de}</Badge>
                      <TrendingUp className="w-3 h-3" />
                      <Badge variant="outline" className="text-xs">{evento.status_para}</Badge>
                    </div>
                  )}
                  
                  {/* Metadados do pedido */}
                  {evento.metadata?.pedido_numero && (
                    <div className="text-xs text-muted-foreground mt-2 bg-muted/50 rounded-md p-2">
                      <span className="font-medium">Pedido:</span> {evento.metadata.pedido_numero}
                      {evento.metadata.pedido_externo && (
                        <span className="ml-2 font-mono text-xs">({evento.metadata.pedido_externo})</span>
                      )}
                    </div>
                  )}
                  
                  {/* Metadados da demanda */}
                  {evento.metadata?.data_entrega && (
                    <div className="text-xs text-muted-foreground mt-2 bg-muted/50 rounded-md p-2">
                      <span className="font-medium">Entrega:</span> {new Date(evento.metadata.data_entrega).toLocaleDateString('pt-BR')}
                      {evento.metadata.status && (
                        <span className="ml-2">• Status: {evento.metadata.status}</span>
                      )}
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
