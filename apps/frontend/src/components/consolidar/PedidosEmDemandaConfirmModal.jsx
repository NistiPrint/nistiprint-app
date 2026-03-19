import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { AlertTriangle, Package, Calendar, CheckCircle2 } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

/**
 * Modal de confirmação quando pedidos já estão em demandas ativas
 */
export default function PedidosEmDemandaConfirmModal({
  open,
  onOpenChange,
  pedidosEmDemanda,
  pedidosLivres,
  onConfirmar,
  onRemoverDuplicados,
  onCancelar
}) {
  const [acaoSelecionada, setAcaoSelecionada] = useState('remover'); // 'remover', 'prosseguir', 'cancelar'

  if (!pedidosEmDemanda || pedidosEmDemanda.length === 0) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-amber-600">
            <AlertTriangle className="w-6 h-6" />
            Pedidos Já Estão em Demandas Ativas
          </DialogTitle>
          <DialogDescription>
            {pedidosEmDemanda.length} de {pedidosEmDemanda.length + (pedidosLivres?.length || 0)} pedidos selecionados já estão vinculados a demandas em andamento.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Alerta */}
          <Alert variant="warning" className="border-amber-200 bg-amber-50">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            <AlertTitle className="text-amber-800">Atenção</AlertTitle>
            <AlertDescription className="text-amber-700">
              Um pedido pode estar em múltiplas demandas, mas isso pode causar inconsistências no controle de estoque e produção.
            </AlertDescription>
          </Alert>

          {/* Tabela de Pedidos em Demanda */}
          <div className="border rounded-lg">
            <div className="bg-muted/50 px-4 py-3 border-b">
              <h4 className="font-semibold text-sm flex items-center gap-2">
                <Package className="w-4 h-4" />
                Pedidos Já Vinculados ({pedidosEmDemanda.length})
              </h4>
            </div>
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/30">
                  <TableHead>Pedido</TableHead>
                  <TableHead>ID Externo</TableHead>
                  <TableHead>Demanda Atual</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Entrega</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pedidosEmDemanda.map((pedido, index) => (
                  <TableRow key={index}>
                    <TableCell className="font-semibold text-blue-700">
                      {pedido.numero_pedido || `#${pedido.pedido_id}`}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {pedido.codigo_externo}
                    </TableCell>
                    <TableCell>
                      <div className="text-sm font-medium">{pedido.demanda_descricao}</div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {pedido.demanda_id?.substring(0, 8)}...
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">
                        {pedido.demanda_status?.replace('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {pedido.data_entrega ? (
                        <div className="flex items-center gap-1 text-sm">
                          <Calendar className="w-3 h-3 text-muted-foreground" />
                          {new Date(pedido.data_entrega).toLocaleDateString('pt-BR')}
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-sm">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pedidos Livres (se houver) */}
          {pedidosLivres && pedidosLivres.length > 0 && (
            <div className="border rounded-lg bg-green-50 border-green-200">
              <div className="bg-green-100 px-4 py-3 border-b border-green-200">
                <h4 className="font-semibold text-sm flex items-center gap-2 text-green-800">
                  <CheckCircle2 className="w-4 h-4" />
                  Pedidos Disponíveis ({pedidosLivres.length})
                </h4>
              </div>
              <div className="px-4 py-3 text-sm text-green-700">
                {pedidosLivres.length} {pedidosLivres.length === 1 ? 'pedido está' : 'pedidos estão'} livres e podem ser consolidados normalmente.
              </div>
            </div>
          )}

          {/* Opções de Ação */}
          <div className="space-y-3 border-t pt-4">
            <h4 className="font-semibold text-sm">O que deseja fazer?</h4>
            
            <div className="space-y-2">
              <label className="flex items-start gap-3 p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors">
                <input
                  type="radio"
                  name="acao"
                  value="remover"
                  checked={acaoSelecionada === 'remover'}
                  onChange={() => setAcaoSelecionada('remover')}
                  className="mt-1"
                />
                <div>
                  <div className="font-medium text-sm">Remover pedidos duplicados automaticamente</div>
                  <div className="text-xs text-muted-foreground">
                    Prosseguir apenas com os {pedidosLivres?.length || 0} pedidos livres
                  </div>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors">
                <input
                  type="radio"
                  name="acao"
                  value="prosseguir"
                  checked={acaoSelecionada === 'prosseguir'}
                  onChange={() => setAcaoSelecionada('prosseguir')}
                  className="mt-1"
                />
                <div>
                  <div className="font-medium text-sm">Prosseguir mesmo assim</div>
                  <div className="text-xs text-muted-foreground">
                    Incluir todos os {pedidosEmDemanda.length + (pedidosLivres?.length || 0)} pedidos (pode causar inconsistências)
                  </div>
                </div>
              </label>

              <label className="flex items-start gap-3 p-3 rounded-lg border cursor-pointer hover:bg-muted/50 transition-colors">
                <input
                  type="radio"
                  name="acao"
                  value="cancelar"
                  checked={acaoSelecionada === 'cancelar'}
                  onChange={() => setAcaoSelecionada('cancelar')}
                  className="mt-1"
                />
                <div>
                  <div className="font-medium text-sm">Cancelar e revisar seleção</div>
                  <div className="text-xs text-muted-foreground">
                    Voltar para a lista de pedidos e fazer uma nova seleção
                  </div>
                </div>
              </label>
            </div>
          </div>
        </div>

        <DialogFooter className="border-t pt-4 mt-4">
          <Button variant="outline" onClick={onCancelar}>
            Cancelar
          </Button>
          <Button
            onClick={acaoSelecionada === 'remover' ? onRemoverDuplicados : onConfirmar}
            disabled={!acaoSelecionada}
            className={
              acaoSelecionada === 'prosseguir' ? 'bg-amber-600 hover:bg-amber-700' :
              'bg-blue-600 hover:bg-blue-700'
            }
          >
            {acaoSelecionada === 'remover' && `Prosseguir com ${pedidosLivres?.length || 0} Pedidos`}
            {acaoSelecionada === 'prosseguir' && 'Prosseguir com Todos (Arriscado)'}
            {acaoSelecionada === 'cancelar' && 'Cancelar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
