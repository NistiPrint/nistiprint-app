import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CheckCircle2, Save, TriangleAlert } from 'lucide-react';

export interface ErpLink {
  id: string;
  erp_integration_id: number;
  erp_store_id: string;
  store_name?: string;
  nf_emission_mode?: string;
  erp?: { id: number; instance_name: string; module_id: string };
}

export interface NfEmitterBannerProps {
  defaultNfeLinkId: string;
  nfeLinks: ErpLink[];
  saving: boolean;
  onSave: (linkId: string) => void;
}

export function NfEmitterBanner({ defaultNfeLinkId, nfeLinks, saving, onSave }: NfEmitterBannerProps) {
  const [selected, setSelected] = useState(defaultNfeLinkId);

  useEffect(() => {
    setSelected(defaultNfeLinkId);
  }, [defaultNfeLinkId]);

  const resolvedLink =
    defaultNfeLinkId !== 'none'
      ? nfeLinks.find((link) => String(link.id) === defaultNfeLinkId)
      : null;
  const isConfigured = !!resolvedLink;

  return (
    <div className={`rounded-md border px-3 py-2 ${isConfigured ? 'bg-emerald-50/60' : 'bg-amber-50/70'}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {isConfigured ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          ) : (
            <TriangleAlert className="h-4 w-4 shrink-0 text-amber-600" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-medium">NF</div>
            <div className="truncate text-xs text-muted-foreground">
              {resolvedLink
                ? `${resolvedLink.erp?.instance_name ?? 'Bling'} / shop.id ${resolvedLink.erp_store_id}`
                : 'Selecione o Bling emissor'}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Select value={selected} onValueChange={setSelected}>
            <SelectTrigger className="h-8 w-full sm:w-[230px]">
              <SelectValue placeholder="Emissor de NF" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Nenhum</SelectItem>
              {nfeLinks.map((link) => (
                <SelectItem key={link.id} value={String(link.id)}>
                  {link.erp?.instance_name ?? 'Bling'} / {link.erp_store_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" disabled={saving || selected === defaultNfeLinkId} onClick={() => onSave(selected)}>
            <Save className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export default NfEmitterBanner;
