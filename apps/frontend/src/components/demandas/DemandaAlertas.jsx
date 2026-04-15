import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Package,
  TrendingDown,
  X
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

/**
 * Componente que exibe alertas de uma demanda específica
 * Usado no dashboard de demanda
 */
export default function DemandaAlertas({ demandaId }) {
  const [alertas, setAlertas] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (demandaId) {
      carregarAlertas();
    }
  }, [demandaId]);

  async function carregarAlertas() {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/demandas/${demandaId}/alertas`);
      const data = await response.json();
      
      if (data.success) {
        setAlertas(data.data.alertas || []);
      } else {
        toast.error('Erro ao carregar alertas');
      }
    } catch (error) {
      console.error('Erro ao buscar alertas:', error);
    } finally {
      setLoading(false);
    }
  }

  async function resolverAlerta(alertaId) {
    try {
      const response = await fetch(`/api/v2/demandas/${demandaId}/alertas/${alertaId}/resolver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (response.ok) {
        toast.success('Alerta resolvido');
        carregarAlertas(); // Recarregar lista
      } else {
        toast.error('Erro ao resolver alerta');
      }
    } catch (error) {
      toast.error('Erro de conexão');
    }
  }

  function getSeverityIcon(severidade) {
    switch (severidade) {
      case 'alta':
        return <AlertTriangle className="w-5 h-5 text-red-600" />;
      case 'media':
        return <AlertCircle className="w-5 h-5 text-amber-600" />;
      case 'baixa':
        return <Clock className="w-5 h-5 text-blue-600" />;
      default:
        return <AlertCircle className="w-5 h-5 text-gray-600" />;
    }
  }

  function getSeverityColor(severidade) {
    switch (severidade) {
      case 'alta':
        return 'bg-red-50 border-red-200';
      case 'media':
        return 'bg-amber-50 border-amber-200';
      case 'baixa':
        return 'bg-blue-50 border-blue-200';
      default:
        return 'bg-gray-50 border-gray-200';
    }
  }

  function getTipoIcon(tipo) {
    switch (tipo) {
      case 'PEDIDO_CANCELADO':
        return <X className="w-4 h-4" />;
      case 'ESTOQUE_INSUFICIENTE':
        return <TrendingDown className="w-4 h-4" />;
      case 'DEMANDA_ATRASADA':
        return <Clock className="w-4 h-4" />;
      default:
        return <AlertCircle className="w-4 h-4" />;
    }
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Alertas
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Clock className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (alertas.length === 0) {
    return null; // Não renderiza se não há alertas
  }

  return (
    <Card className="border-red-200 bg-red-50/30">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-red-800">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Alertas ({alertas.length})
          </div>
          <Badge variant="destructive">
            Requer atenção
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px] pr-4">
          <div className="space-y-3">
            {alertas.map((alerta) => (
              <Alert 
                key={alerta.id} 
                className={`border-l-4 ${
                  alerta.severidade === 'alta' ? 'border-red-500 bg-red-50' :
                  alerta.severidade === 'media' ? 'border-amber-500 bg-amber-50' :
                  'border-blue-500 bg-blue-50'
                }`}
              >
                <div className="flex items-start gap-3">
                  {getSeverityIcon(alerta.severidade)}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {getTipoIcon(alerta.tipo_alerta)}
                      <AlertTitle className="text-sm font-semibold">{alerta.titulo}</AlertTitle>
                      <Badge variant="secondary" className="text-xs">
                        {alerta.tipo_alerta.replace('_', ' ')}
                      </Badge>
                    </div>
                    <AlertDescription className="text-sm">
                      {alerta.mensagem}
                      
                      {/* Dados de impacto */}
                      {alerta.dados_impacto && alerta.dados_impacto.itens_afetados && (
                        <div className="mt-2 p-2 bg-white/50 rounded text-xs">
                          <p className="font-semibold mb-1">Impacto nos itens:</p>
                          {alerta.dados_impacto.itens_afetados.slice(0, 3).map((item, idx) => (
                            <div key={idx} className="flex justify-between py-1">
                              <span>{item.sku}</span>
                              <span className="font-mono">
                                {item.qtd_original} → {item.qtd_nova} (-{item.qtd_pedido_cancelado})
                              </span>
                            </div>
                          ))}
                          {alerta.dados_impacto.itens_afetados.length > 3 && (
                            <p className="text-muted-foreground text-xs mt-1">
                              +{alerta.dados_impacto.itens_afetados.length - 3} outros itens
                            </p>
                          )}
                        </div>
                      )}
                      
                      {/* Ações */}
                      {alerta.requer_acao && !alerta.resolvido && (
                        <div className="flex gap-2 mt-3">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => resolverAlerta(alerta.id)}
                            className="text-xs"
                          >
                            <CheckCircle2 className="w-3 h-3 mr-1" />
                            Marcar como Resolvido
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {/* Navegar para edição da demanda */}}
                            className="text-xs"
                          >
                            <Package className="w-3 h-3 mr-1" />
                            Revisar Demanda
                          </Button>
                        </div>
                      )}
                      
                      {/* Status de resolvido */}
                      {alerta.resolvido && (
                        <div className="flex items-center gap-2 mt-2 text-green-600 text-xs">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Resolvido em {new Date(alerta.resolvido_em).toLocaleString('pt-BR')}</span>
                        </div>
                      )}
                    </AlertDescription>
                  </div>
                </div>
              </Alert>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
