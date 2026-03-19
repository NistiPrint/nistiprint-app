import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  AlertTriangle, 
  AlertCircle, 
  CheckCircle2, 
  Package, 
  Calendar,
  Zap,
  AlertOctagon,
  Clock,
  ExternalLink,
  X
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Dashboard de Alertas de Produção
 * Exibe alertas de pedidos órfãos, demandas atrasadas, etc.
 */
export default function AlertasDashboard({ compact = false }) {
  const navigate = useNavigate();
  const [alertas, setAlertas] = useState([]);
  const [resumo, setResumo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedAlert, setExpandedAlert] = useState(null);

  useEffect(() => {
    carregarAlertas();
  }, []);

  async function carregarAlertas() {
    setLoading(true);
    try {
      const response = await fetch('/api/v2/alertas/producao');
      const data = await response.json();
      
      if (data.success) {
        setAlertas(data.data.alertas || []);
        setResumo(data.data.resumo || null);
      } else {
        toast.error('Erro ao carregar alertas');
      }
    } catch (error) {
      console.error('Erro ao buscar alertas:', error);
    } finally {
      setLoading(false);
    }
  }

  function getSeverityIcon(severidade) {
    switch (severidade) {
      case 'alta':
        return <AlertOctagon className="w-5 h-5 text-red-600" />;
      case 'media':
        return <AlertTriangle className="w-5 h-5 text-amber-600" />;
      case 'baixa':
        return <AlertCircle className="w-5 h-5 text-blue-600" />;
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
      case 'PEDIDOS_ORFAOS':
        return <Package className="w-4 h-4" />;
      case 'DEMANDAS_ATRASADAS':
        return <Calendar className="w-4 h-4" />;
      case 'FLEX_URGENTE':
        return <Zap className="w-4 h-4" />;
      case 'ESTOQUE_INSUFICIENTE':
        return <AlertCircle className="w-4 h-4" />;
      default:
        return <AlertCircle className="w-4 h-4" />;
    }
  }

  function handleVerPedidosOrfaos() {
    navigate('/vendas/unified-orders?has_demanda=false');
  }

  function handleVerDemandasAtrasadas() {
    navigate('/producao/demanda');
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Alertas de Produção
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

  // Versão compacta (badge no header)
  if (compact) {
    return (
      <>
        {resumo?.total_alertas > 0 && (
          <Badge 
            className="bg-red-500 text-white hover:bg-red-600 cursor-pointer"
            onClick={() => document.getElementById('alertas-panel')?.scrollIntoView({ behavior: 'smooth' })}
          >
            <AlertTriangle className="w-3 h-3 mr-1" />
            {resumo.total_alertas}
          </Badge>
        )}
      </>
    );
  }

  return (
    <Card id="alertas-panel">
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            Alertas de Produção
          </div>
          {resumo && (
            <div className="flex gap-2">
              {resumo.alta > 0 && (
                <Badge className="bg-red-500 text-white">
                  {resumo.alta}
                </Badge>
              )}
              {resumo.media > 0 && (
                <Badge className="bg-amber-500 text-white">
                  {resumo.media}
                </Badge>
              )}
              {resumo.baixa > 0 && (
                <Badge variant="secondary">
                  {resumo.baixa}
                </Badge>
              )}
            </div>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {alertas.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <CheckCircle2 className="w-12 h-12 text-green-600 mb-4" />
            <h3 className="text-lg font-semibold mb-2">Tudo em ordem!</h3>
            <p className="text-muted-foreground text-sm">
              Não há alertas de produção no momento.
            </p>
          </div>
        ) : (
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-3">
              {alertas.map((alerta, index) => (
                <div
                  key={index}
                  className={`rounded-lg border p-4 ${getSeverityColor(alerta.severidade)}`}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      {getSeverityIcon(alerta.severidade)}
                      <div>
                        <div className="flex items-center gap-2">
                          {getTipoIcon(alerta.tipo_alerta)}
                          <h4 className="font-semibold text-sm">{alerta.titulo}</h4>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">
                          {alerta.mensagem}
                        </p>
                      </div>
                    </div>
                    <Badge 
                      className={
                        alerta.severidade === 'alta' ? 'bg-red-500 text-white' :
                        alerta.severidade === 'media' ? 'bg-amber-500 text-white' :
                        'bg-blue-500 text-white'
                      }
                    >
                      {alerta.quantidade}
                    </Badge>
                  </div>

                  {/* Botão de expandir */}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setExpandedAlert(expandedAlert === index ? null : index)}
                    className="w-full text-xs"
                  >
                    {expandedAlert === index ? (
                      <>
                        <X className="w-3 h-3 mr-1" />
                        Ocultar Detalhes
                      </>
                    ) : (
                      <>
                        <ExternalLink className="w-3 h-3 mr-1" />
                        Ver Detalhes ({alerta.quantidade})
                      </>
                    )}
                  </Button>

                  {/* Detalhes Expandidos */}
                  {expandedAlert === index && alerta.detalhes && (
                    <div className="mt-3 pt-3 border-t space-y-2">
                      {/* Pedidos Órfãos */}
                      {alerta.tipo_alerta === 'PEDIDOS_ORFAOS' && alerta.detalhes.pedidos && (
                        <div className="space-y-2">
                          <p className="text-xs font-semibold">Últimos pedidos sem demanda:</p>
                          {alerta.detalhes.pedidos.slice(0, 5).map((pedido, idx) => (
                            <div key={idx} className="flex items-center justify-between text-xs p-2 bg-white rounded">
                              <div>
                                <span className="font-semibold text-blue-700">{pedido.numero_pedido}</span>
                                <span className="text-muted-foreground ml-2">{pedido.cliente}</span>
                              </div>
                              <div className="text-right">
                                <span className="text-amber-600 font-medium">{pedido.horas_sem_demanda}h</span>
                                <span className="text-muted-foreground text-xs block">sem demanda</span>
                              </div>
                            </div>
                          ))}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleVerPedidosOrfaos}
                            className="w-full mt-2"
                          >
                            <Package className="w-3 h-3 mr-2" />
                            Ver Todos Pedidos Órfãos
                          </Button>
                        </div>
                      )}

                      {/* Demandas Atrasadas */}
                      {alerta.tipo_alerta === 'DEMANDAS_ATRASADAS' && alerta.detalhes.demandas && (
                        <div className="space-y-2">
                          <p className="text-xs font-semibold">Demandas atrasadas:</p>
                          {alerta.detalhes.demandas.slice(0, 5).map((demanda, idx) => (
                            <div key={idx} className="flex items-center justify-between text-xs p-2 bg-white rounded">
                              <div>
                                <span className="font-semibold">{demanda.descricao}</span>
                                <span className="text-muted-foreground ml-2">
                                  {demanda.dias_atraso} dias atraso
                                </span>
                              </div>
                              <div className="text-right">
                                <Badge variant="secondary" className="text-xs">
                                  {demanda.progresso}% concluído
                                </Badge>
                              </div>
                            </div>
                          ))}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleVerDemandasAtrasadas}
                            className="w-full mt-2"
                          >
                            <Calendar className="w-3 h-3 mr-2" />
                            Ver Demandas
                          </Button>
                        </div>
                      )}

                      {/* Pedidos FLEX */}
                      {alerta.tipo_alerta === 'FLEX_URGENTE' && alerta.detalhes.pedidos_flex && (
                        <div className="space-y-2">
                          <p className="text-xs font-semibold">Pedidos FLEX urgentes:</p>
                          {alerta.detalhes.pedidos_flex.slice(0, 5).map((pedido, idx) => (
                            <div key={idx} className="flex items-center justify-between text-xs p-2 bg-white rounded">
                              <div>
                                <span className="font-semibold text-blue-700">{pedido.numero_pedido}</span>
                                <span className="text-muted-foreground ml-2">{pedido.cliente}</span>
                              </div>
                              <div className="text-right">
                                <span className="text-red-600 font-medium">{Math.round(pedido.horas_restantes)}h</span>
                                <span className="text-muted-foreground text-xs block">restantes</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
