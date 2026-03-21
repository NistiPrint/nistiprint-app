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
import { Store, Building2, Link, AlertCircle } from 'lucide-react';
import * as integracaoCanalService from '@/services/integracaoCanalService';

/**
 * Modal para criar/editar vínculo de integração
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
    integration_id: 'none',  // Usa 'none' como valor padrão
    is_primary: false,
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
          integration_id: vinculoEdit.integration_id?.toString() || 'none',
          is_primary: vinculoEdit.is_primary || false,
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

      const payload = {
        canal_venda_id: parseInt(formData.canal_venda_id),
        bling_loja_id: parseInt(formData.bling_loja_id),
        plataforma_nome: formData.plataforma_nome.toLowerCase(),
        integration_id: formData.integration_id ? parseInt(formData.integration_id) : null,
        is_primary: formData.is_primary,
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
        integration_id: 'none',
        is_primary: false,
        is_active: true
      });
    } catch (err) {
      setError(err.message || 'Erro ao salvar vínculo');
    } finally {
      setLoading(false);
    }
  }

  const isEditing = !!vinculoEdit;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
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
            <Label htmlFor="canal_venda">Canal de Venda</Label>
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
            <Label htmlFor="plataforma">Plataforma</Label>
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
            <Label htmlFor="bling_loja_id">ID da Loja no Bling</Label>
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
            <p className="text-xs text-muted-foreground">
              ID da loja conforme aparece no Bling (ex: 204047801, 205218967)
            </p>
          </div>

          {/* Integração */}
          <div className="space-y-2">
            <Label htmlFor="integration_id">Instância de Integração (opcional)</Label>
            <div className="relative">
              <Building2 className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Select
                value={formData.integration_id || 'none'}
                onValueChange={(value) => setFormData(prev => ({ ...prev, integration_id: value === 'none' ? '' : value }))}
              >
                <SelectTrigger className="pl-9">
                  <SelectValue placeholder="Selecione a integração" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Apenas Bling (sem integração direta)</SelectItem>
                  {integracoes.map((integ) => (
                    <SelectItem key={integ.id} value={integ.id.toString()}>
                      {integ.instance_name} ({integ.module_id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

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
