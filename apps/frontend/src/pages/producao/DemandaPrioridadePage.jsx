import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useRealtimePrioritizedDemandas } from '@/lib/hooks/useRealtimePrioritizedDemandas';
import { AlertCircle, Clock, Eye, Flame } from 'lucide-react';
import { Link } from 'react-router-dom';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

function DemandaPrioridadePage() {
  const { prioritizedItems, loading, error } = useRealtimePrioritizedDemandas();
  const orderedItems = [...prioritizedItems].sort((a, b) => {
    const am = a?.demanda_info?.coleta_contexto?.minutos_ate_proxima_coleta;
    const bm = b?.demanda_info?.coleta_contexto?.minutos_ate_proxima_coleta;
    if (typeof am === 'number' && typeof bm === 'number') return am - bm;
    if (typeof am === 'number') return -1;
    if (typeof bm === 'number') return 1;
    return (b?.prioridade_calculada || 0) - (a?.prioridade_calculada || 0);
  });

  const getPriorityColor = (priority) => {
    if (priority >= 80) return 'border-red-500 bg-red-100';
    if (priority >= 60) return 'border-orange-500 bg-orange-100';
    if (priority >= 40) return 'border-yellow-500 bg-yellow-100';
    return 'border-gray-300 bg-gray-50';
  };

  const getPriorityBadge = (priority) => {
    if (priority >= 2000) return <Badge className="bg-purple-700 text-white ml-2 animate-pulse border-none">Máxima (Flex)</Badge>;
    if (priority >= 1000) return <Badge variant="destructive" className="ml-2 animate-pulse">Máxima (Atrasado)</Badge>;
    if (priority >= 80) return <Badge variant="destructive" className="ml-2">Alta</Badge>;
    if (priority >= 60) return <Badge className="bg-orange-500 text-white ml-2">Média</Badge>;
    if (priority >= 40) return <Badge className="bg-yellow-500 text-black ml-2">Normal</Badge>;
    return <Badge variant="secondary" className="ml-2">Baixa</Badge>;
  };

  if (loading) return <div className="text-center py-4">Carregando Fila de Prioridades...</div>;
  if (error) return <div className="text-center py-4 text-red-500">Erro: {error}</div>;

  return (
    <div className="container mx-auto py-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Flame className="h-8 w-8 text-orange-500" /> Fila de Prioridades
        </h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Itens de Demanda Prioritários</CardTitle>
        </CardHeader>
        <CardContent>
          {prioritizedItems.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Flame className="mx-auto h-12 w-12 text-muted-foreground/50 mb-4" />
              <p className="text-lg">Nenhum item prioritário encontrado no momento.</p>
              <p className="text-sm">Verifique as demandas ou aguarde novas entradas.</p>
            </div>
          ) : (
            <ScrollArea className="h-[70vh]">
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                {orderedItems.map(item => (
                  <Card 
                    key={item.id} 
                    className={`shadow-sm hover:shadow-md transition-shadow border-l-4 border-l-gray-300`}
                  >
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-lg font-bold flex items-center gap-2 flex-wrap">
                          {item.item_descricao}
                          {item.demanda_info?.is_flex && (
                            <Badge className="bg-purple-600 text-white border-none text-[10px] h-5">
                              <Flame className="w-3 h-3 mr-1" />
                              FLEX
                            </Badge>
                          )}
                          {getPriorityBadge(item.prioridade_calculada)}
                          {item.demanda_info?.canal_venda_plataforma && (
                            <Badge 
                              variant="outline" 
                              style={{ backgroundColor: item.demanda_info.canal_venda_color, color: 'white' }} 
                              className="text-xs ml-2"
                            >
                              {item.demanda_info.canal_venda_plataforma}
                            </Badge>
                          )}
                        </CardTitle>
                        {item.demanda_info?.observacoes && (
                          <div className="text-sm text-gray-500 flex items-center gap-1">
                            <AlertCircle className="h-4 w-4 text-blue-500" />
                            {item.demanda_info.observacoes.substring(0, 20)}...
                          </div>
                        )}
                      </div>
                    </CardHeader>
                    <CardContent className="text-sm space-y-2">
                      <p>
                        <span className="font-medium">Demanda:</span> {item.demanda_info?.nome}
                      </p>
                      <p className="flex items-center gap-1">
                        <Clock className="h-4 w-4" />
                        <span className="font-medium">Entrega:</span> {format(new Date(item.demanda_info?.data_entrega), 'dd/MM/yyyy', { locale: ptBR })}
                        {item.demanda_info?.horario_coleta && ` às ${item.demanda_info.horario_coleta}`}
                      </p>
                      <p>
                        <span className="font-medium">Canal:</span> {item.demanda_info?.canal_venda_nome}
                      </p>
                      {typeof item.demanda_info?.coleta_contexto?.minutos_ate_proxima_coleta === 'number' && (
                        <p>
                          <span className="font-medium">Próxima coleta:</span> {item.demanda_info?.coleta_contexto?.proxima_coleta_horario || '-'} ({item.demanda_info.coleta_contexto.minutos_ate_proxima_coleta} min)
                        </p>
                      )}
                      {item.demanda_info?.tipo_demanda === 'Empresas' && (
                        <div className="text-xs text-gray-700 space-y-1 mt-2">
                          <p className="font-medium">Empresa: {item.demanda_info.empresa_cliente_nome}</p>
                          <p>Status Interação: {item.demanda_info.empresa_interacao_status}</p>
                          {item.demanda_info.empresa_wire_o_cor && (
                            <span className="inline-flex items-center text-xs mr-2">
                              Wire-o: <span style={{ backgroundColor: item.demanda_info.empresa_wire_o_cor }} className="w-3 h-3 rounded-full ml-1 border border-gray-300"></span>
                            </span>
                          )}
                          {item.demanda_info.empresa_elastico_cor && (
                            <span className="inline-flex items-center text-xs">
                              Elástico: <span style={{ backgroundColor: item.demanda_info.empresa_elastico_cor }} className="w-3 h-3 rounded-full ml-1 border border-gray-300"></span>
                            </span>
                          )}
                        </div>
                      )}
                      <p>
                        <span className="font-medium">Quantidade:</span> {item.quantidade_total}
                      </p>
                      <div className="flex justify-end mt-4">
                        <Link to={`/producao/demanda/${item.demanda_info?.id}/dashboard`}>
                          <Button variant="outline" size="sm">
                            <Eye className="h-3 w-3 mr-1" /> Ver Demanda
                          </Button>
                        </Link>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default DemandaPrioridadePage;
