import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Building2, Pencil, Trash2 } from 'lucide-react';

export interface ErpLink {
  id: string;
  erp_integration_id: number;
  erp_store_id: string;
  store_name?: string;
  nf_emission_mode?: string;
  ingest_origin_mode?: string;
  marketplace_module_id?: string;
  erp?: { id: number; instance_name: string; module_id: string };
  marketplace?: { id: number; instance_name: string; module_id: string };
}

export interface LinkTableProps {
  links: ErpLink[];
  viewMode: 'erp' | 'marketplace';
  defaultNfeLinkId?: string;
  onEdit?: (link: ErpLink) => void;
  onDelete?: (link: ErpLink) => void;
}

const NF_LABELS: Record<string, string> = {
  bling: 'NF Bling',
  local: 'NF local',
  disabled: 'Sem NF',
};

function ingestLabel(mode?: string) {
  if (mode === 'marketplace_direct') return 'Webhook marketplace';
  if (mode === 'erp_only_dummy') return 'Dummy via Bling';
  return 'Webhook Bling';
}

export function LinkTable({ links, viewMode, defaultNfeLinkId, onEdit, onDelete }: LinkTableProps) {
  if (links.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-md border border-dashed py-5 text-sm text-muted-foreground">
        <Building2 className="h-4 w-4" />
        Nenhum vinculo
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {links.map((link) => {
        const counterpart =
          viewMode === 'erp'
            ? link.marketplace?.instance_name ?? link.marketplace_module_id ?? 'Origem'
            : link.erp?.instance_name ?? `Bling ${link.erp_integration_id}`;
        const isDefault = String(link.id) === defaultNfeLinkId;

        return (
          <div key={link.id} className="flex flex-col gap-2 rounded-md border px-3 py-2 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="truncate text-sm font-medium">{counterpart}</span>
                {isDefault && (
                  <Badge className="h-5 bg-emerald-100 px-1.5 text-[10px] text-emerald-700 hover:bg-emerald-100">
                    NF padrao
                  </Badge>
                )}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <code className="rounded bg-muted px-1.5 py-0.5">{link.erp_store_id}</code>
                <span>{ingestLabel(link.ingest_origin_mode)}</span>
                <span>{NF_LABELS[link.nf_emission_mode ?? ''] ?? link.nf_emission_mode ?? 'NF ?'}</span>
              </div>
            </div>

            {viewMode === 'marketplace' && (
              <div className="flex items-center justify-end gap-1">
                <Button variant="ghost" size="sm" onClick={() => onEdit?.(link)}>
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => onDelete?.(link)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default LinkTable;
