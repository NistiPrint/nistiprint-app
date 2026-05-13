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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Edit2,
  Trash2,
  Crown,
  Building2,
  Store,
  Link,
  AlertCircle,
  HelpCircle,
  CheckCircle2,
  BellOff
} from 'lucide-react';

/**
 * Tabela de vínculos de lojas por canal
 * Mostra separadamente as integrações Bling (ERP) e Marketplace.
 * 
 * Cada linha representa um vínculo entre:
 * - Uma loja no Bling (identificada pelo ID)
 * - Uma instância de integração Bling (ERP)
 * - Uma instância de integração Marketplace
 */
export default function LojaVinculoTable({
  vinculos = [],
  integracoes = [],
  onEdit,
  onDelete,
  onToggleWebhooks
}) {
  const getIntegrationName = (integrationId) => {
    if (!integrationId) return null;
    const integracao = integracoes.find(i => i.id === integrationId);
    return integracao?.instance_name || `Integração ${integrationId}`;
  };

  const getIntegrationModule = (integrationId) => {
    if (!integrationId) return null;
    const integracao = integracoes.find(i => i.id === integrationId);
    return integracao?.module_id;
  };

  return (
    <Table>
      <TableHeader>
        <TableRow className="bg-muted/30">
          <TableHead className="w-[80px]">
            <div className="flex items-center gap-1">
              Primária
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Vínculo principal é usado como padrão</p>
                </TooltipContent>
              </Tooltip>
            </div>
          </TableHead>
          <TableHead>Loja Bling</TableHead>
          <TableHead>
            <div className="flex items-center gap-1">
              <Building2 className="w-3 h-3" />
              Bling (ERP)
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Conta Bling usada para API de pedidos</p>
                  <p className="text-xs mt-1 text-muted-foreground">
                    Gerencie tokens na aba "Integrações"
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </TableHead>
          <TableHead>
            <div className="flex items-center gap-1">
              <Link className="w-3 h-3" />
              Marketplace
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Integração com a plataforma de venda</p>
                  <p className="text-xs mt-1 text-muted-foreground">
                    Gerencie tokens na aba "Integrações"
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </TableHead>
          <TableHead className="w-[100px]">
            <div className="flex items-center gap-1">
              Status
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">
                    <strong>Completo:</strong> Ambas integrações vinculadas<br/>
                    <strong>Incompleto:</strong> Falta uma ou ambas
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </TableHead>
          <TableHead className="w-[120px]">Webhooks</TableHead>
          <TableHead className="w-[100px] text-right">Ações</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {vinculos.map((vinculo) => {
          const blingIntegrationId = vinculo.bling_integration_id;
          const marketplaceIntegrationId = vinculo.marketplace_integration_id;
          const hasBoth = blingIntegrationId && marketplaceIntegrationId;
          const hasOnlyBling = blingIntegrationId && !marketplaceIntegrationId;
          const hasOnlyMarketplace = marketplaceIntegrationId && !blingIntegrationId;

          return (
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
                  {blingIntegrationId ? (
                    <div className="flex flex-col">
                      <span className="text-sm font-medium">
                        {getIntegrationName(blingIntegrationId)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {getIntegrationModule(blingIntegrationId)}
                      </span>
                    </div>
                  ) : (
                    <Badge variant="secondary" className="text-xs gap-1">
                      <AlertCircle className="w-3 h-3" />
                      Não vinculado
                    </Badge>
                  )}
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <Link className="w-4 h-4 text-muted-foreground" />
                  {marketplaceIntegrationId ? (
                    <div className="flex flex-col">
                      <span className="text-sm font-medium">
                        {getIntegrationName(marketplaceIntegrationId)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {getIntegrationModule(marketplaceIntegrationId)}
                      </span>
                    </div>
                  ) : (
                    <Badge variant="secondary" className="text-xs gap-1">
                      <AlertCircle className="w-3 h-3" />
                      Não vinculado
                    </Badge>
                  )}
                </div>
              </TableCell>
              <TableCell>
                {hasBoth ? (
                  <Badge variant="secondary" className="bg-green-100 text-green-800 gap-1">
                    <CheckCircle2 className="w-3 h-3" />
                    Completo
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {hasOnlyBling ? 'Falta Marketplace' : hasOnlyMarketplace ? 'Falta Bling' : 'Incompleto'}
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2"
                      onClick={() => onToggleWebhooks?.(vinculo)}
                    >
                      {vinculo.process_webhooks === false ? (
                        <Badge variant="outline" className="gap-1 border-amber-500 text-amber-700">
                          <BellOff className="w-3 h-3" />
                          Ignora
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="gap-1">
                          Processa
                        </Badge>
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="text-xs">
                      Clique para {vinculo.process_webhooks === false ? 'processar' : 'ignorar'} webhooks deste vinculo.
                    </p>
                  </TooltipContent>
                </Tooltip>
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
          );
        })}
      </TableBody>
    </Table>
  );
}
