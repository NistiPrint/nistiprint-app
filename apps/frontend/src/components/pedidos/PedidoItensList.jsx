import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Package } from 'lucide-react';

/**
 * Lista de itens do pedido
 */
export default function PedidoItensList({ itens }) {
  if (!itens || itens.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Package className="w-5 h-5" />
            Itens do Pedido
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-center py-8">
            Nenhum item encontrado
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Package className="w-5 h-5" />
          Itens do Pedido ({itens.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead className="w-[100px]">Qtd</TableHead>
              <TableHead>Produto</TableHead>
              <TableHead>SKU</TableHead>
              <TableHead className="text-right">Unitário</TableHead>
              <TableHead className="text-right">Subtotal</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {itens.map((item, index) => (
              <TableRow key={item.id || index}>
                <TableCell className="font-bold">
                  {Number(item.quantidade).toFixed(0)}
                </TableCell>
                <TableCell className="font-medium">
                  {item.descricao || 'Produto sem descrição'}
                  {item.produto?.nome && (
                    <div className="text-xs text-muted-foreground mt-1">
                      {item.produto.nome}
                    </div>
                  )}
                </TableCell>
                <TableCell className="font-mono text-sm">
                  {item.sku_externo || '-'}
                </TableCell>
                <TableCell className="text-right">
                  {new Intl.NumberFormat('pt-BR', {
                    style: 'currency',
                    currency: 'BRL'
                  }).format(item.preco_unitario || 0)}
                </TableCell>
                <TableCell className="text-right font-bold">
                  {new Intl.NumberFormat('pt-BR', {
                    style: 'currency',
                    currency: 'BRL'
                  }).format(item.subtotal || 0)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
