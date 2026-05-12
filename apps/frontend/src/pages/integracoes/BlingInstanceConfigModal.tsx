/**
 * Modal de Configuração de Instância Bling
 * 
 * Permite configurar:
 * - ID do campo customizado de personalização
 * - Vínculos com marketplaces (Shopee, Amazon, etc.)
 * - ID da loja Bling para cada marketplace
 */

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

// Componentes UI
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

// Ícones
import { Building2, Plus, ShoppingCart, Trash2, X } from 'lucide-react';

// Tipos
interface MarketplaceInstance {
  id: number;
  module_id: string;
  instance_name: string;
  is_active: boolean;
  catalog_only?: boolean;
}

interface MarketplaceModule {
  id: string;
  name: string;
  category?: string;
  tipo?: string;
}

interface ErpLink {
  id: string;
  erp_integration_id: number;
  marketplace_integration_id: number | null;
  marketplace_module_id?: string;
  erp_store_id: string;
  store_name: string;
  marketplace?: MarketplaceInstance;
}

interface BlingInstance {
  id: number;
  module_id: string;
  instance_name: string;
  is_active: boolean;
  config?: any;
}

interface BlingInstanceConfigModalProps {
  integrationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const BlingInstanceConfigModal: React.FC<BlingInstanceConfigModalProps> = ({
  integrationId,
  open,
  onOpenChange,
}) => {
  // Estados
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [blingInstance, setBlingInstance] = useState<BlingInstance | null>(null);
  const [links, setLinks] = useState<ErpLink[]>([]);
  const [marketplaceInstances, setMarketplaceInstances] = useState<MarketplaceInstance[]>([]);
  const [marketplaceModules, setMarketplaceModules] = useState<MarketplaceModule[]>([]);
  
  // Estado para formulário de novo vínculo (inline)
  const [showAddForm, setShowAddForm] = useState(false);
  const [newLink, setNewLink] = useState({
    marketplace_integration_id: 'none',
    marketplace_module_id: 'shopee',
    erp_store_id: '',
    store_name: '',
  });

  // Estado para campo customizado
  const [customFieldId, setCustomFieldId] = useState<string>('2797770');
  const [companyId, setCompanyId] = useState<string>('');

  // Carregar dados
  useEffect(() => {
    if (open) {
      load_data();
    }
  }, [open, integrationId]);

  const load_data = async () => {
    try {
      setLoading(true);

      // Carregar instância Bling
      const blingRes = await fetch(`/api/v2/marketplace/installed/${integrationId}`);
      if (blingRes.ok) {
        const blingData = await blingRes.json();
        setBlingInstance(blingData.installation);
        
        if (blingData.installation?.config?.id_campo_personalizado) {
          setCustomFieldId(String(blingData.installation.config.id_campo_personalizado));
        }
        setCompanyId(String(blingData.installation?.config?.company_id || ''));
      }

      // Carregar vínculos existentes
      const linksRes = await fetch(`/api/v2/erp-links/erp/${integrationId}/links`);
      if (linksRes.ok) {
        const linksData = await linksRes.json();
        setLinks(linksData.data || []);
      }

      // Carregar instâncias de marketplace disponíveis
      const marketplaceRes = await fetch('/api/v2/marketplace/instances?active=true');
      if (marketplaceRes.ok) {
        const marketplaceData = await marketplaceRes.json();
        setMarketplaceInstances(marketplaceData.data || []);
      }

      const modulesRes = await fetch('/api/v2/marketplace/modules');
      if (modulesRes.ok) {
        const modulesData = await modulesRes.json();
        const modules = (modulesData.modules || []).filter((mod: MarketplaceModule) =>
          mod.tipo === 'MARKETPLACE' || mod.category === 'Marketplace'
        );
        setMarketplaceModules(modules);
      }
    } catch (error) {
      console.error('Erro ao carregar dados:', error);
      toast.error('Erro ao carregar dados');
    } finally {
      setLoading(false);
    }
  };

  // Salvar configuração
  const handleSave = async () => {
    try {
      setSaving(true);

      await fetch(`/api/v2/marketplace/installed/${integrationId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          config: {
            ...(blingInstance?.config || {}),
            id_campo_personalizado: parseInt(customFieldId),
            company_id: companyId?.trim() || null,
          },
        }),
      });

      toast.success('Configurações salvas com sucesso!');
      onOpenChange(false);
    } catch (error) {
      console.error('Erro ao salvar:', error);
      toast.error('Erro ao salvar configurações');
    } finally {
      setSaving(false);
    }
  };

  // Adicionar vínculo
  const handleAddLink = async () => {
    try {
      const res = await fetch(`/api/v2/erp-links/erp/${integrationId}/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          marketplace_module_id: newLink.marketplace_module_id,
          ...(newLink.marketplace_integration_id !== 'none'
            ? { marketplace_integration_id: parseInt(newLink.marketplace_integration_id) }
            : {}),
          erp_store_id: newLink.erp_store_id,
          store_name: newLink.store_name || undefined,
        }),
      });

      if (res.ok) {
        toast.success('Vínculo adicionado com sucesso!');
        setShowAddForm(false);
        setNewLink({
          marketplace_integration_id: 'none',
          marketplace_module_id: 'shopee',
          erp_store_id: '',
          store_name: '',
        });
        load_data();
      } else {
        const error = await res.json();
        toast.error(error.message || 'Erro ao adicionar vínculo');
      }
    } catch (error) {
      console.error('Erro ao adicionar vínculo:', error);
      toast.error('Erro ao adicionar vínculo');
    }
  };

  // Remover vínculo
  const handleRemoveLink = async (linkId: string) => {
    if (!confirm('Tem certeza que deseja remover este vínculo?')) return;

    try {
      const res = await fetch(`/api/v2/erp-links/links/${linkId}`, {
        method: 'DELETE',
      });

      if (res.ok) {
        toast.success('Vínculo removido com sucesso!');
        load_data();
      } else {
        toast.error('Erro ao remover vínculo');
      }
    } catch (error) {
      console.error('Erro ao remover vínculo:', error);
      toast.error('Erro ao remover vínculo');
    }
  };

  const filteredMarketplaces = marketplaceInstances.filter(
    (m) => m.module_id === newLink.marketplace_module_id
  );

  const marketplaceModuleOptions = marketplaceModules.length > 0
    ? marketplaceModules
    : [
        { id: 'shopee', name: 'Shopee' },
        { id: 'amazonfba_classic', name: 'Amazon FBA Classic' },
        { id: 'amazon_fulfillment', name: 'Amazon Fulfillment' },
        { id: 'mercadolivre', name: 'Mercado Livre' },
        { id: 'shein', name: 'Shein' },
        { id: 'tiktokshop', name: 'TikTok Shop' },
        { id: 'kwai', name: 'Kwai' },
        { id: 'lojaintegrada', name: 'Loja Integrada' },
        { id: 'magazineluiza', name: 'Magazine Luiza' },
      ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Configurar Bling - {blingInstance?.instance_name}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-6 py-4">
          <Alert>
            <AlertDescription>
              <strong>Como funciona:</strong> Configure qual loja Bling (loja_id) corresponde 
              a cada marketplace para identificar pedidos personalizados.
            </AlertDescription>
          </Alert>

          {/* Campo Customizado */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Personalização de Produtos
            </h3>
            <div className="grid gap-2">
              <Label htmlFor="customFieldId">ID do Campo Customizado</Label>
              <Input
                id="customFieldId"
                type="number"
                value={customFieldId}
                onChange={(e) => setCustomFieldId(e.target.value)}
                placeholder="Ex: 2797770"
              />
              <p className="text-sm text-muted-foreground">
                ID do campo no Bling que indica se um produto é personalizado.
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="companyId">Company ID da Conta Bling</Label>
              <Input
                id="companyId"
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value)}
                placeholder="Ex: fa3c40c3e6ec60129f2c1a063872b816"
              />
              <p className="text-sm text-muted-foreground">
                Usado para identificar a conta de origem no webhook (`companyId`).
              </p>
            </div>
          </div>

          {/* Vínculos com Marketplaces */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <ShoppingCart className="h-5 w-5" />
                Vínculos com Marketplaces
              </h3>
              <Button size="sm" onClick={() => setShowAddForm(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Adicionar Vínculo
              </Button>
            </div>

            {showAddForm && (
              <div className="border rounded-lg p-4 space-y-4 bg-muted/50">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold">Novo Vínculo</h4>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowAddForm(false);
                      setNewLink({
                        marketplace_integration_id: 'none',
                        marketplace_module_id: 'shopee',
                        erp_store_id: '',
                        store_name: '',
                      });
                    }}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>

                <div className="grid gap-4">
                  <div className="grid gap-2">
                    <Label>Módulo</Label>
                    <Select
                      value={newLink.marketplace_module_id}
                      onValueChange={(value) =>
                        setNewLink({ ...newLink, marketplace_module_id: value, marketplace_integration_id: 'none' })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione" />
                      </SelectTrigger>
                      <SelectContent>
                        {marketplaceModuleOptions.map((mod) => (
                          <SelectItem key={mod.id} value={mod.id}>
                            {mod.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="grid gap-2">
                    <Label>Instância do Marketplace</Label>
                    <Select
                      value={newLink.marketplace_integration_id}
                      onValueChange={(value) =>
                        setNewLink({ ...newLink, marketplace_integration_id: value })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Selecione" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">Nenhuma instancia instalada</SelectItem>
                        {filteredMarketplaces.map((m) => (
                          <SelectItem key={m.id} value={String(m.id)}>
                            {m.instance_name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="grid gap-2">
                    <Label>ID da Loja Bling</Label>
                    <Input
                      type="number"
                      value={newLink.erp_store_id}
                      onChange={(e) =>
                        setNewLink({ ...newLink, erp_store_id: e.target.value })
                      }
                      placeholder="Ex: 204047801"
                    />
                  </div>

                  <div className="grid gap-2">
                    <Label>Nome (opcional)</Label>
                    <Input
                      value={newLink.store_name}
                      onChange={(e) =>
                        setNewLink({ ...newLink, store_name: e.target.value })
                      }
                      placeholder="Ex: Shopee Antiga"
                    />
                  </div>

                  <Button onClick={handleAddLink} className="w-full">
                    Adicionar Vínculo
                  </Button>
                </div>
              </div>
            )}

            {links.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground border rounded-lg">
                <Building2 className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Nenhum vínculo configurado</p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Marketplace</TableHead>
                    <TableHead>Instância</TableHead>
                    <TableHead>ID Loja Bling</TableHead>
                    <TableHead>Nome</TableHead>
                    <TableHead className="w-[100px]">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {links.map((link) => (
                    <TableRow key={link.id}>
                      <TableCell>
                        <Badge variant="outline">
                          {link.marketplace?.module_id || link.marketplace_module_id || 'N/A'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {link.marketplace?.instance_name || 'Catalogo'}
                        {link.marketplace?.catalog_only && (
                          <Badge variant="secondary" className="ml-2">sem instalacao</Badge>
                        )}
                      </TableCell>
                      <TableCell className="font-mono">{link.erp_store_id}</TableCell>
                      <TableCell>{link.store_name || '-'}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveLink(link.id)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Salvando...' : 'Salvar Configurações'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default BlingInstanceConfigModal;
