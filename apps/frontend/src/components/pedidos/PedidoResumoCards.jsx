import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { 
  Package, 
  User, 
  Truck, 
  DollarSign,
  Calendar,
  Zap
} from 'lucide-react';
import { formatAppDate } from '@/lib/dateTime';

/**
 * Cards de resumo do pedido (3 colunas)
 */
export default function PedidoResumoCards({ pedido }) {
  const { financeiro, cliente, logistica, datas } = pedido;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      {/* Resumo Financeiro */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Total do Pedido
          </CardTitle>
          <DollarSign className="w-4 h-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {new Intl.NumberFormat('pt-BR', {
              style: 'currency',
              currency: financeiro?.moeda || 'BRL'
            }).format(financeiro?.total || 0)}
          </div>
          <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
            <Package className="w-3 h-3" />
            <span>{financeiro?.total_itens || 0} {financeiro?.total_itens === 1 ? 'item' : 'itens'}</span>
            <span>•</span>
            <span>{financeiro?.total_quantidade || 0} un.</span>
          </div>
        </CardContent>
      </Card>

      {/* Dados do Cliente */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Cliente
          </CardTitle>
          <User className="w-4 h-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-lg font-semibold truncate">
            {cliente?.nome || 'Não informado'}
          </div>
          <div className="flex flex-col gap-1 mt-2 text-xs text-muted-foreground">
            {cliente?.documento && (
              <span>{cliente.documento}</span>
            )}
            {cliente?.telefone && (
              <span>{cliente.telefone}</span>
            )}
            {cliente?.email && (
              <span className="truncate">{cliente.email}</span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Dados de Envio */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Entrega
          </CardTitle>
          <Truck className="w-4 h-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <span className="font-medium">
              {datas?.limite_envio 
                ? formatAppDate(datas.limite_envio)
                : 'Não definido'
              }
            </span>
          </div>
          <div className="flex items-center gap-2 mt-2">
            {logistica?.is_flex && (
              <Badge className="bg-amber-500 text-white text-xs gap-1">
                <Zap className="w-3 h-3 fill-white" />
                FLEX
              </Badge>
            )}
            {logistica?.servico_logistico && (
              <span className="text-xs text-muted-foreground truncate">
                {logistica.servico_logistico}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
