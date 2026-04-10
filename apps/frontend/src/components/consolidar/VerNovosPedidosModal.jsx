import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertTriangle, Clock, ShoppingCart } from 'lucide-react';
import { useEffect, useState } from 'react';

/**
 * Modal para visualizar pedidos novos que chegaram após edição do rascunho.
 */
export default function VerNovosPedidosModal({
  open,
  onOpenChange,
  demandaId,
  onConfirmar,
  buscarPedidosNovos,
}) {
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && demandaId) {
      carregarPedidos();
    }
  }, [open, demandaId]);

  const carregarPedidos = async () => {
    setLoading(true);
    try {
      const dados = await buscarPedidosNovos(demandaId);
      setPedidos(dados);
    } catch (err) {
      console.error('Erro ao carregar pedidos:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmar = async () => {
    const sucesso = await onConfirmar(demandaId);
    if (sucesso) {
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-orange-500" />
            {pedidos.length} Novo(s) Pedido(s) Após Edição
          </DialogTitle>
          <DialogDescription>
            Estes pedidos chegaram depois que você editou o rascunho. Revise e confirme a inclusão.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {loading ? (
            <div className="text-center py-8 text-gray-500">
              Carregando pedidos...
            </div>
          ) : pedidos.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              Nenhum pedido novo encontrado.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Pedido</TableHead>
                  <TableHead>Código Externo</TableHead>
                  <TableHead>Valor</TableHead>
                  <TableHead>Data</TableHead>
                  <TableHead>Chegou</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pedidos.map((item) => {
                  const pedido = item.pedidos;
                  const chegouEm = item.adicionado_em
                    ? new Date(item.adicionado_em)
                    : new Date();

                  // Calcular há quanto tempo chegou
                  const agora = new Date();
                  const diffMinutos = Math.floor((agora - chegouEm) / (1000 * 60));
                  const chegouTexto =
                    diffMinutos < 1
                      ? 'Agora mesmo'
                      : diffMinutos < 60
                      ? `Há ${diffMinutos} min`
                      : `Há ${Math.floor(diffMinutos / 60)}h`;

                  return (
                    <TableRow key={item.id}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          <ShoppingCart className="h-4 w-4 text-gray-400" />
                          {pedido?.numero_pedido || `#${pedido?.id}`}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs font-mono text-gray-500">
                        {pedido?.codigo_pedido_externo || '-'}
                      </TableCell>
                      <TableCell>
                        {pedido?.total_pedido
                          ? `R$ ${parseFloat(pedido.total_pedido).toFixed(2)}`
                          : '-'}
                      </TableCell>
                      <TableCell className="text-sm">
                        {pedido?.data_venda
                          ? new Date(pedido.data_venda).toLocaleDateString('pt-BR')
                          : '-'}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={diffMinutos < 30 ? 'destructive' : 'secondary'}
                          className="text-[10px]"
                        >
                          <Clock className="h-3 w-3 mr-1" />
                          {chegouTexto}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            onClick={handleConfirmar}
            disabled={pedidos.length === 0}
            className="bg-green-600 hover:bg-green-700"
          >
            <AlertTriangle className="h-4 w-4 mr-2" />
            Confirmar Inclusão ({pedidos.length})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
