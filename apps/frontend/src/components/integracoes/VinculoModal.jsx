import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Store, Building2, Link, AlertCircle, Package, HelpCircle, Bell } from 'lucide-react';
import * as integracaoCanalService from '@/services/integracaoCanalService';

/**
 * Modal para criar/editar vínculo de integração
 * Agora com seleção separada para Bling (ERP) e Marketplace
 */
export default function VinculoModal({
  open,
  onOpenChange,
  vinculoEdit,
  plataformaFilter,
  onSuccess
}) {
  const [loading, setLoading] = useState(false);
  const [canais, setCanais] = useState([]);
  const [integracoes, setIntegracoes] = useState([]);
  const [formData, setFormData] = useState({
    canal_venda_id: '',
    bling_loja_id: '',
    plataforma_nome: plataformaFilter || '',
    bling_integration_id: 'none',
    marketplace_integration_id: 'none',
    is_primary: false,
    process_webhooks: true,
    is_active: true
  });
  const [error, setError] = useState('');

  // Carregar canais e integrações ao abrir modal
  useEffect(() => {
    if (open) {
      carregarDados();
      if (vinculoEdit) {
        setFormData({
          canal_venda_id: vinculoEdit.canal_venda_id?.toString() || '',
          bling_loja_id: vinculoEdit.bling_loja_id?.toString() || '',
          plataforma_nome: vinculoEdit.plataforma_nome || '',
          bling_integration_id: vinculoEdit.bling_integration_id?.toString() || 'none',
          marketplace_integration_id: vinculoEdit.marketplace_integration_id?.toString() || 'none',
          is_primary: vinculoEdit.is_primary || false,
          process_webhooks: vinculoEdit.process_webhooks !== false,
          is_active: vinculoEdit.is_active !== false
        });
      } else if (plataformaFilter) {
        setFormData(prev => ({ ...prev, plataforma_nome: plataformaFilter }));
      }
    }
  }, [open, vinculoEdit, plataformaFilter]);

  async function carregarDados() {
    try {
      const [canaisData, integracoesData] = await Promise.all([
        integracaoCanalService.listarCanais(),
        integracaoCanalService.listarIntegracoes()
      ]);
      setCanais(canaisData);
      setIntegracoes(integracoesData);
    } catch (err) {
      console.error('Erro ao carregar dados:', err);
    }
  }

  async function handleSubmit() {
    setError('');
    setLoading(true);

    try {
      // Validações
      if (!formData.canal_venda_id) {
        throw new Error('Selecione um canal de venda');
      }
      if (!formData.bling_loja_id) {
        throw new Error('Informe o ID da loja no Bling');
      }
      if (!formData.plataforma_nome) {
        throw new Error('Informe a plataforma');
      }

      // Pelo menos uma integração deve ser selecionada
      const hasBling = formData.bling_integration_id && formData.bling_integration_id !== 'none';
      const hasMarketplace = formData.marketplace_integration_id && formData.marketplace_integration_id !== 'none';
      
      if (!hasBling && !hasMarketplace) {
        throw new Error('Selecione pelo menos uma integração (Bling ou Marketplace)');
      }

      const payload = {
        canal_venda_id: parseInt(formData.canal_venda_id),
        bling_loja_id: parseInt(formData.bling_loja_id),
        plataforma_nome: formData.plataforma_nome.toLowerCase(),
        bling_integration_id: hasBling ? parseInt(formData.bling_integration_id) : null,
        marketplace_integration_id: hasMarketplace ? parseInt(formData.marketplace_integration_id) : null,
        is_primary: formData.is_primary,
        process_webhooks: formData.process_webhooks,
        is_active: formData.is_active
      };

      if (vinculoEdit) {
        await integracaoCanalService.atualizarVinculo(vinculoEdit.id, payload);
      } else {
        await integracaoCanalService.criarVinculo(payload);
      }

      onSuccess?.();
      onOpenChange(false);
      setFormData({
        canal_venda_id: '',
        bling_loja_id: '',
        plataforma_nome: plataformaFilter || '',
        bling_integration_id: 'none',
        marketplace_integration_id: 'none',
        is_primary: false,
        process_webhooks: true,
        is_active: true
      });
    } catch (err) {
      setError(err.message || 'Erro ao salvar vínculo');
    } finally {
      setLoading(false);
    }
  }

  const isEditing = !!vinculoEdit;

  // Filtrar integrações por tipo
  const blingIntegrations = integracoes.filter(i => i.module_id === 'bling');
  const marketplaceIntegrations = integracoes.filter(i => i.module_id !== 'bling');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? 'Editar Vínculo' : 'Novo Vínculo de Integração'}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? 'Atualize as configurações do vínculo entre canal e loja Bling'
              : 'Configure um novo vínculo entre um canal de venda e uma loja no Bling'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Canal de Venda */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="canal_venda">Canal de Venda</Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p className="text-xs">
                    <strong>Canal de venda interno</strong> que será vinculado a esta loja Bling.
                  </p>
                  <p className="text-xs mt-1 text-muted-foreground">
                    Os canais são configurados em "Cadastros → Canais de Venda" e representam suas frentes de venda.
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            <Select
              value={formData.canal_venda_id}
              onValueChange={(value) => setFormData(prev => ({ ...prev, canal_venda_id: value }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Selecione o canal" />
              </SelectTrigger>
              <SelectContent>
                {canais.map((canal) => (
                  <SelectItem key={canal.id} value={canal.id.toString()}>
                    {canal.nome} {canal.slug && `(${canal.slug})`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Plataforma */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="plataforma">Plataforma</Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p className="text-xs">
                    <strong>Plataforma de marketplace</strong> (Shopee, Amazon, etc.) onde seus produtos são vendidos.
                  </p>
                  <p className="text-xs mt-1 text-muted-foreground">
                    Esta plataforma será vinculada a uma loja no Bling e a uma instância de integração.
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            <Select
              value={formData.plataforma_nome}
              onValueChange={(value) => setFormData(prev => ({ ...prev, plataforma_nome: value }))}
              disabled={!!plataformaFilter}
            >
              <SelectTrigger>
                <SelectValue placeholder="Selecione a plataforma" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="shopee">Shopee</SelectItem>
                <SelectItem value="amazon">Amazon</SelectItem>
                <SelectItem value="mercadolivre">Mercado Livre</SelectItem>
                <SelectItem value="shein">Shein</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* ID da Loja Bling */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="bling_loja_id">ID da Loja no Bling</Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p className="text-xs">
                    Número da loja conforme aparece no Bling. Você encontra este ID na URL ou nas configurações da loja no Bling.
                  </p>
                  <p className="text-xs mt-1 font-mono bg-muted px-1 py-0.5 rounded">Ex: 204047801</p>
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="relative">
              <Store className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                id="bling_loja_id"
                type="number"
                placeholder="Ex: 204047801"
                className="pl-9"
                value={formData.bling_loja_id}
                onChange={(e) => setFormData(prev => ({ ...prev, bling_loja_id: e.target.value }))}
              />
            </div>
          </div>

          {/* Divider */}
          <div className="relative py-2">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-muted"></div>
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                <Building2 className="w-3 h-3 inline mr-1" />
                Integrações
              </span>
            </div>
          </div>

          {/* Integração Bling (ERP) */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="bling_integration_id">
                Integração Bling (ERP)
              </Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p className="text-xs">
                    <strong>Selecione uma instância Bling</strong> que será usada para consultar e atualizar pedidos deste vínculo.
                  </p>
                  <p className="text-xs mt-2 text-muted-foreground">
                    Cada instância representa uma conta Bling diferente. Você pode instalar o Bling múltiplas vezes na aba "Integrações".
                  </p>
                  <p className="text-xs mt-1 text-amber-600 font-medium">
                    ⚠️ Deixe "Nenhuma" se quiser usar apenas o marketplace.
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="relative">
              <Building2 className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Select
                value={formData.bling_integration_id || 'none'}
                onValueChange={(value) => setFormData(prev => ({ ...prev, bling_integration_id: value === 'none' ? null : value }))}
              >
                <SelectTrigger className="pl-9">
                  <SelectValue placeholder="Selecione a instância Bling" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Nenhuma (apenas marketplace)</SelectItem>
                  {blingIntegrations.map((integ) => (
                    <SelectItem key={integ.id} value={integ.id.toString()}>
                      {integ.instance_name} {integ.cnpj && `(CNPJ: ${integ.cnpj})`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Integração Marketplace */}
          <div className="space-y-2">
            <div className="flex items-center gap-1">
              <Label htmlFor="marketplace_integration_id">
                Integração Marketplace
              </Label>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p className="text-xs">
                    <strong>Selecione uma instância de marketplace</strong> para este vínculo.
                  </p>
                  <p className="text-xs mt-2 text-muted-foreground">
                    Cada instância representa uma conta diferente da plataforma ({formData.plataforma_nome || 'marketplace'}). Você pode instalar múltiplas contas na aba "Integrações".
                  </p>
                  <p className="text-xs mt-1 text-amber-600 font-medium">
                    ⚠️ Deixe "Nenhuma" se quiser usar apenas o Bling.
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
            <div className="relative">
              <Package className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Select
                value={formData.marketplace_integration_id || 'none'}
                onValueChange={(value) => setFormData(prev => ({ ...prev, marketplace_integration_id: value === 'none' ? null : value }))}
              >
                <SelectTrigger className="pl-9">
                  <SelectValue placeholder="Selecione a instância de marketplace" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Nenhuma (apenas Bling)</SelectItem>
                  {marketplaceIntegrations.map((integ) => (
                    <SelectItem key={integ.id} value={integ.id.toString()}>
                      {integ.instance_name} ({integ.module_id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Alerta se nenhuma integração selecionada */}
          {(!formData.bling_integration_id || formData.bling_integration_id === 'none') &&
           (!formData.marketplace_integration_id || formData.marketplace_integration_id === 'none') && (
            <Alert className="bg-amber-50 border-amber-200">
              <AlertCircle className="h-4 w-4 text-amber-600" />
              <AlertDescription className="text-amber-800 text-xs">
                <strong>Atenção:</strong> Selecione pelo menos uma instância de integração (Bling ou Marketplace) para este vínculo.
              </AlertDescription>
            </Alert>
          )}

          {/* Is Primary */}
          <div className="flex items-center justify-between space-x-2 rounded-lg border p-3">
            <div className="flex-1 space-y-0.5">
              <Label className="text-sm font-medium">Vínculo Principal</Label>
              <p className="text-xs text-muted-foreground">
                Este será o vínculo padrão para esta plataforma
              </p>
            </div>
            <Switch
              checked={formData.is_primary}
              onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_primary: checked }))}
            />
          </div>

          {/* Process Webhooks */}
          <div className="flex items-center justify-between space-x-2 rounded-lg border p-3">
            <div className="flex-1 space-y-0.5">
              <Label className="text-sm font-medium flex items-center gap-2">
                <Bell className="h-4 w-4 text-muted-foreground" />
                Processar webhooks
              </Label>
              <p className="text-xs text-muted-foreground">
                Desligue quando esta conta Bling receber pedidos duplicados de uma loja ja processada por outro vinculo
              </p>
            </div>
            <Switch
              checked={formData.process_webhooks}
              onCheckedChange={(checked) => setFormData(prev => ({ ...prev, process_webhooks: checked }))}
            />
          </div>

          {/* Is Active */}
          <div className="flex items-center justify-between space-x-2 rounded-lg border p-3">
            <div className="flex-1 space-y-0.5">
              <Label className="text-sm font-medium">Ativo</Label>
              <p className="text-xs text-muted-foreground">
                Vínculos inativos não são usados no processamento
              </p>
            </div>
            <Switch
              checked={formData.is_active}
              onCheckedChange={(checked) => setFormData(prev => ({ ...prev, is_active: checked }))}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {loading ? 'Salvando...' : (isEditing ? 'Atualizar' : 'Criar Vínculo')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
