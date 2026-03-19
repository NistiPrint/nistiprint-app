import React from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Edit2, 
  Trash2, 
  Crown, 
  Building2,
  Store,
  Link
} from 'lucide-react';

/**
 * Tabela de vínculos de lojas por canal
 */
export default function LojaVinculoTable({ 
  vinculos = [], 
  integracoes = [],
  onEdit, 
  onDelete 
}) {
  const getIntegrationName = (integrationId) => {
    if (!integrationId) return 'Apenas Bling';
    const integracao = integracoes.find(i => i.id === integrationId);
    return integracao?.instance_name || `Integration ${integrationId}`;
  };

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/30">
          <TableHead className="w-[80px]">Primária</TableHead>
          <TableHead>Loja Bling</TableHead>
          <TableHead>Integração</TableHead>
          <TableHead className="w-[100px]">Status</TableHead>
          <TableHead className="w-[100px] text-right">Ações</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {vinculos.map((vinculo) => (
          <TableRow key={vinculo.id}>
            <TableCell>
              {vinculo.is_primary ? (
                <Badge variant="default" className="bg-amber-500 gap-1">
                  <Crown className="w-3 h-3" />
                  Principal
                </Badge>
              ) : (
                <span className="text-muted-foreground text-sm">-</span>
              )}
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <Store className="w-4 h-4 text-muted-foreground" />
                <div className="flex flex-col">
                  <span className="font-mono text-sm font-medium">
                    {vinculo.bling_loja_id}
                  </span>
                  {vinculo.plataforma_nome && (
                    <span className="text-xs text-muted-foreground capitalize">
                      {vinculo.plataforma_nome}
                    </span>
                  )}
                </div>
              </div>
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm">
                  {getIntegrationName(vinculo.integration_id)}
                </span>
              </div>
            </TableCell>
            <TableCell>
              <Badge 
                variant={vinculo.is_active ? "secondary" : "outline"} 
                className={vinculo.is_active ? "bg-green-100 text-green-800" : ""}
              >
                {vinculo.is_active ? "Ativo" : "Inativo"}
              </Badge>
            </TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => onEdit(vinculo)}
                >
                  <Edit2 className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-destructive hover:text-destructive"
                  onClick={() => onDelete(vinculo)}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
