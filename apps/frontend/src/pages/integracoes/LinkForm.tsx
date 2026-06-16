import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Save, X } from 'lucide-react';

export interface ErpLink {
  id: string;
  erp_integration_id: number;
  erp_store_id: string;
  store_name?: string;
  nf_emission_mode?: string;
  erp?: { id: number; instance_name: string; module_id: string };
}

export interface BlingAccount {
  id: number;
  instance_name: string;
  module_id: string;
}

export interface LinkFormData {
  erp_integration_id: number;
  erp_store_id: string;
  store_name: string;
  ingest_origin_mode: string;
  nf_emission_mode: string;
}

export interface LinkFormProps {
  editingLink?: ErpLink | null;
  blingAccounts: BlingAccount[];
  onSave: (data: LinkFormData) => void;
  onCancel: () => void;
}

export function LinkForm({
  editingLink,
  blingAccounts,
  onSave,
  onCancel,
}: LinkFormProps) {
  const [erpIntegrationId, setErpIntegrationId] = useState<string>('');
  const [erpStoreId, setErpStoreId] = useState('');
  const [ingestOriginMode, setIngestOriginMode] = useState('erp_bling');
  const [nfEmissionMode, setNfEmissionMode] = useState('bling');
  const [storeName, setStoreName] = useState('');

  useEffect(() => {
    if (editingLink) {
      setErpIntegrationId(String(editingLink.erp_integration_id));
      setErpStoreId(editingLink.erp_store_id);
      setIngestOriginMode(
        (editingLink as Record<string, unknown>).ingest_origin_mode as string ??
          'erp_bling',
      );
      setNfEmissionMode(editingLink.nf_emission_mode ?? 'bling');
      setStoreName(editingLink.store_name ?? '');
    } else {
      setErpIntegrationId('');
      setErpStoreId('');
      setIngestOriginMode('erp_bling');
      setNfEmissionMode('bling');
      setStoreName('');
    }
  }, [editingLink]);

  function handleSubmit() {
    if (!erpIntegrationId) {
      toast.error('Selecione a conta Bling.');
      return;
    }

    if (!erpStoreId.trim()) {
      toast.error('Informe o shop.id.');
      return;
    }

    onSave({
      erp_integration_id: Number(erpIntegrationId),
      erp_store_id: erpStoreId.trim(),
      store_name: storeName.trim(),
      ingest_origin_mode: ingestOriginMode,
      nf_emission_mode: nfEmissionMode,
    });
  }

  return (
    <div className="rounded-lg border bg-muted/40 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-sm font-semibold">
          {editingLink ? 'Editar vínculo' : 'Novo vínculo com ERP'}
        </h4>
        <Button variant="ghost" size="icon" onClick={onCancel}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="bling-account">Conta Bling</Label>
          <Select value={erpIntegrationId} onValueChange={setErpIntegrationId}>
            <SelectTrigger id="bling-account">
              <SelectValue placeholder="Selecione a conta" />
            </SelectTrigger>
            <SelectContent>
              {blingAccounts.map((account) => (
                <SelectItem key={account.id} value={String(account.id)}>
                  {account.instance_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="shop-id">shop.id</Label>
          <Input
            id="shop-id"
            value={erpStoreId}
            onChange={(e) => setErpStoreId(e.target.value)}
            placeholder="Ex: 204047801"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="ingest-origin">Origem do pedido</Label>
          <Select value={ingestOriginMode} onValueChange={setIngestOriginMode}>
            <SelectTrigger id="ingest-origin">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="erp_bling">Pedido vem via Bling</SelectItem>
              <SelectItem value="erp_only_dummy">
                Canal sem integração (via Bling)
              </SelectItem>
              <SelectItem value="marketplace_direct">
                Pedido vem direto do marketplace
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="nf-emission">Emissão de NF</Label>
          <Select value={nfEmissionMode} onValueChange={setNfEmissionMode}>
            <SelectTrigger id="nf-emission">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bling">Bling</SelectItem>
              <SelectItem value="local">Local</SelectItem>
              <SelectItem value="disabled">Desativada</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="store-name">Nome interno</Label>
          <Input
            id="store-name"
            value={storeName}
            onChange={(e) => setStoreName(e.target.value)}
            placeholder="Ex: Shopee 01 / Bling 01"
          />
        </div>
      </div>

      <Button className="mt-4 w-full" onClick={handleSubmit}>
        <Save className="mr-1.5 h-4 w-4" />
        Salvar
      </Button>
    </div>
  );
}

export default LinkForm;
