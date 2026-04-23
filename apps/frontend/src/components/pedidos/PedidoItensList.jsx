import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Package, Sparkles } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from '@/components/ui/tooltip';

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
    <TooltipProvider>
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
              <TableHead className="w-[80px]">Qtd</TableHead>
              <TableHead>Produto</TableHead>
              <TableHead className="w-[120px]">SKU</TableHead>
              <TableHead className="w-[100px] text-right">Unitário</TableHead>
              <TableHead className="w-[100px] text-right">Subtotal</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {itens.map((item, index) => {
              const isPersonalizado = item.personalizado || item.is_personalizado;
              return (
              <TableRow
                key={item.id || index}
                className={isPersonalizado
                  ? 'relative bg-purple-50/40 hover:bg-purple-50 border-l-2 border-l-purple-400'
                  : ''
                }
              >
                <TableCell className="font-bold">
                  <div className="flex flex-col items-center">
                    {Number(item.quantidade).toFixed(0)}
                    {isPersonalizado && (
                      <Tooltip>
                        <TooltipTrigger>
                          <Sparkles className="h-3 w-3 text-purple-500 mt-0.5" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <span>Item personalizado</span>
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </TableCell>
                <TableCell className="font-medium">
                  <div className="flex items-start gap-2">
                    <span>{item.descricao || 'Produto sem descrição'}</span>
                    {isPersonalizado && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-purple-300 text-purple-600 bg-purple-50 shrink-0">
                        Personalizado
                      </Badge>
                    )}
                  </div>
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
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
    </TooltipProvider>
  );
}
