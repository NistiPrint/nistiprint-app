import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Card, CardContent } from '@/components/ui/card';
import { 
  Package, 
  ExternalLink, 
  User, 
  Calendar,
  DollarSign,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Tab que exibe pedidos vinculados a uma demanda
 */
export default function DemandaPedidosTab({ demandaId }) {
  const navigate = useNavigate();
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalPedidos, setTotalPedidos] = useState(0);
  const [totalItens, setTotalItens] = useState(0);

  useEffect(() => {
    carregarPedidos();
  }, [demandaId]);

  async function carregarPedidos() {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/demandas/${demandaId}/pedidos`);
      const data = await response.json();
      
      if (data.success) {
        setPedidos(data.data.pedidos || []);
        setTotalPedidos(data.data.total_pedidos || 0);
        setTotalItens(data.data.total_itens || 0);
      } else {
        toast.error(data.message || 'Erro ao carregar pedidos');
      }
    } catch (error) {
      console.error('Erro ao carregar pedidos:', error);
      toast.error('Erro de conexão');
    } finally {
      setLoading(false);
    }
  }

  function handleVerPedido(pedidoId) {
    navigate(`/pedidos/${pedidoId}`);
  }

  function getStatusBadge(status) {
    const statusConfig = {
      'Pendente': { bg: 'bg-amber-500', text: 'Pendente' },
      'Pago': { bg: 'bg-green-500', text: 'Pago' },
      'Em Produção': { bg: 'bg-blue-500', text: 'Em Produção' },
      'Enviado': { bg: 'bg-purple-500', text: 'Enviado' },
      'Entregue': { bg: 'bg-gray-500', text: 'Entregue' },
      'Cancelado': { bg: 'bg-red-500', text: 'Cancelado' }
    };
    
    const config = statusConfig[status?.nome] || { bg: 'bg-gray-500', text: status?.nome || 'Desconhecido' };
    
    return (
      <Badge className={`${config.bg} text-white text-xs`}>
        {config.text}
      </Badge>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Package className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (pedidos.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <AlertCircle className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-lg font-semibold mb-2">Nenhum pedido vinculado</h3>
          <p className="text-muted-foreground">
            Esta demanda não possui pedidos vinculados.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Resumo */}
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1">
          <Package className="w-4 h-4" />
          <span>{totalPedidos} {totalPedidos === 1 ? 'pedido' : 'pedidos'}</span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle2 className="w-4 h-4" />
          <span>{totalItens} {totalItens === 1 ? 'item' : 'itens'}</span>
        </div>
      </div>

      {/* Tabela de Pedidos */}
      <div className="border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead className="w-[120px]">Número</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead className="w-[120px]">Status</TableHead>
              <TableHead className="w-[120px]">Data Venda</TableHead>
              <TableHead className="text-right w-[120px]">Total</TableHead>
              <TableHead className="text-center w-[120px]">Itens</TableHead>
              <TableHead className="text-right w-[100px]">Ações</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pedidos.map((pedido) => (
              <TableRow key={pedido.id} className="hover:bg-muted/30">
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-semibold text-sm text-blue-700">
                      {pedido.numero_pedido}
                    </span>
                    <span className="text-xs text-muted-foreground font-mono">
                      {pedido.codigo_externo}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-medium text-sm">
                      {pedido.cliente?.nome || 'N/A'}
                    </span>
                    {pedido.cliente?.documento && (
                      <span className="text-xs text-muted-foreground">
                        {pedido.cliente.documento}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {getStatusBadge(pedido.status)}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1 text-sm">
                    <Calendar className="w-3 h-3 text-muted-foreground" />
                    {pedido.data_venda 
                      ? new Date(pedido.data_venda).toLocaleDateString('pt-BR')
                      : '-'
                    }
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1 text-sm font-semibold">
                    <DollarSign className="w-3 h-3 text-muted-foreground" />
                    {new Intl.NumberFormat('pt-BR', {
                      style: 'currency',
                      currency: 'BRL'
                    }).format(pedido.total_pedido || 0)}
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  <Badge variant="secondary" className="text-xs">
                    {pedido.qtd_itens_no_pedido} {pedido.qtd_itens_no_pedido === 1 ? 'item' : 'itens'}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleVerPedido(pedido.id)}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
