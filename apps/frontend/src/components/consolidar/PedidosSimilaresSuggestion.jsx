import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Package, Calendar, Percent, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

/**
 * Modal que sugere pedidos similares para consolidação
 */
export default function PedidosSimilaresSuggestion({ 
  pedidoId, 
  open, 
  onOpenChange,
  onConfirmSelection 
}) {
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedPedidos, setSelectedPedidos] = useState([]);

  useEffect(() => {
    if (open && pedidoId) {
      carregarSimilares();
    }
  }, [open, pedidoId]);

  async function carregarSimilares() {
    setLoading(true);
    try {
      const response = await fetch(`/api/v2/consolidar-base/pedidos?pedido_id=${pedidoId}&limit=10`);
      const data = await response.json();
      
      if (data.success) {
        setPedidos(data.data || []);
        setSelectedPedidos([]);
      } else {
        toast.error('Erro ao carregar pedidos similares');
      }
    } catch (error) {
      console.error('Erro ao buscar similares:', error);
      toast.error('Erro de conexão');
    } finally {
      setLoading(false);
    }
  }

  function handleSelectPedido(pedidoId, checked) {
    if (checked) {
      setSelectedPedidos(prev => [...prev, pedidoId]);
    } else {
      setSelectedPedidos(prev => prev.filter(id => id !== pedidoId));
    }
  }

  function handleConfirmar() {
    if (selectedPedidos.length === 0) {
      toast.info('Selecione pelo menos um pedido');
      return;
    }
    
    onConfirmSelection([...selectedPedidos, pedidoId]);
    onOpenChange(false);
  }

  function handleSelecionarTodos() {
    if (selectedPedidos.length === pedidos.length) {
      setSelectedPedidos([]);
    } else {
      setSelectedPedidos(pedidos.map(p => p.pedido_id));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="w-5 h-5" />
            Pedidos Similares Sugeridos
          </DialogTitle>
          <p className="text-sm text-muted-foreground">
            Estes pedidos possuem itens similares e podem ser consolidados juntos para otimizar a produção.
          </p>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Package className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        ) : pedidos.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="w-12 h-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">Nenhum pedido similar encontrado</h3>
            <p className="text-muted-foreground text-sm">
              Não encontramos pedidos com itens similares para este pedido.
            </p>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50">
                    <TableHead className="w-12 text-center">
                      <Checkbox 
                        checked={selectedPedidos.length === pedidos.length && pedidos.length > 0}
                        onCheckedChange={handleSelecionarTodos}
                      />
                    </TableHead>
                    <TableHead>Pedido</TableHead>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Itens em Comum</TableHead>
                    <TableHead>SKUs Comuns</TableHead>
                    <TableHead className="text-center">Similaridade</TableHead>
                    <TableHead>Entrega</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pedidos.map((pedido) => (
                    <TableRow 
                      key={pedido.pedido_id}
                      className={selectedPedidos.includes(pedido.pedido_id) ? 'bg-blue-50/50' : ''}
                    >
                      <TableCell className="text-center">
                        <Checkbox
                          checked={selectedPedidos.includes(pedido.pedido_id)}
                          onCheckedChange={(checked) => handleSelectPedido(pedido.pedido_id, checked)}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-semibold text-sm text-blue-700">
                            {pedido.numero_pedido || '-'}
                          </span>
                          <span className="text-xs text-muted-foreground font-mono">
                            {pedido.codigo_pedido_externo}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm">
                        {pedido.cliente_nome || 'N/A'}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">
                          {pedido.itens_em_comum} {pedido.itens_em_comum === 1 ? 'item' : 'itens'}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                        {pedido.skus_comuns}
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="flex items-center justify-center gap-1">
                          <Percent className="w-3 h-3 text-muted-foreground" />
                          <span className={`font-bold text-sm ${
                            pedido.score_similaridade >= 75 ? 'text-green-600' :
                            pedido.score_similaridade >= 50 ? 'text-amber-600' :
                            'text-red-600'
                          }`}>
                            {pedido.score_similaridade}%
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm">
                        <div className="flex items-center gap-1">
                          <Calendar className="w-3 h-3 text-muted-foreground" />
                          {pedido.data_limite_envio 
                            ? new Date(pedido.data_limite_envio).toLocaleDateString('pt-BR')
                            : '-'
                          }
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <DialogFooter className="border-t pt-4 mt-4">
              <div className="flex items-center justify-between w-full">
                <span className="text-sm text-muted-foreground">
                  {selectedPedidos.length} de {pedidos.length} pedidos selecionados
                </span>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => onOpenChange(false)}>
                    Cancelar
                  </Button>
                  <Button 
                    onClick={handleConfirmar}
                    disabled={selectedPedidos.length === 0}
                    className="bg-blue-600 hover:bg-blue-700"
                  >
                    <Package className="w-4 h-4 mr-2" />
                    Consolidar {selectedPedidos.length + 1} Pedidos
                  </Button>
                </div>
              </div>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
