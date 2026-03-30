import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Package,
  Link,
  Edit2,
  Trash2,
  CheckCircle2,
  XCircle,
  Building2,
  AlertCircle,
  HelpCircle,
  RefreshCw
} from 'lucide-react';
import LojaVinculoTable from './LojaVinculoTable';
import * as integracaoCanalService from '@/services/integracaoCanalService';

/**
 * Card de configuração de integração por plataforma
 * Mostra status separado para Bling (ERP) e Marketplace
 */
export default function IntegracaoCard({
  plataforma,
  vinculos = [],
  integracoes = [],
  canais = [],
  onEditVinculo,
  onDeleteVinculo,
  onAddVinculo
}) {
  const [renewingId, setRenewingId] = useState(null);
  const [renewError, setRenewError] = useState(null);

  // Agrupar vínculos por canal
  const vinculosPorCanal = vinculos.reduce((acc, vinculo) => {
    const canalNome = vinculo.canal_nome || `Canal ${vinculo.canal_venda_id}`;
    if (!acc[canalNome]) {
      acc[canalNome] = {
        canal_id: vinculo.canal_venda_id,
        canal_slug: vinculo.canal_slug,
        canal_ativo: vinculo.canal_ativo,
        vinculos: []
      };
    }
    acc[canalNome].vinculos.push(vinculo);
    return acc;
  }, {});

  // Obter ícone da plataforma
  const getPlatformIcon = (nome) => {
    const icons = {
      shopee: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
      amazon: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
      mercadolivre: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
      shein: 'https://app.nistiprint.com.br/assets/img/shein.svg'
    };
    return icons[nome?.toLowerCase()] || null;
  };

  // Obter cor da plataforma
  const getPlatformColor = (nome) => {
    const colors = {
      shopee: 'bg-orange-500',
      amazon: 'bg-blue-600',
      mercadolivre: 'bg-blue-400',
      shein: 'bg-black'
    };
    return colors[nome?.toLowerCase()] || 'bg-gray-500';
  };

  // Calcular estatísticas
  const totalVinculos = vinculos.length;
  const vinculosAtivos = vinculos.filter(v => v.is_active).length;
  const vinculosCompletos = vinculos.filter(v => v.bling_integration_id && v.marketplace_integration_id).length;
  const vinculosIncompletos = totalVinculos - vinculosCompletos;
  
  // Verificar se há integração marketplace ativa
  const marketplaceIntegrations = integracoes.filter(i => i.module_id === plataforma.toLowerCase());
  const integracaoAtiva = marketplaceIntegrations.find(i => i.is_active);

  // Função para renovar token (apenas Shopee)
  async function handleRenewToken(instanceId) {
    if (!window.confirm('Deseja renovar o token desta integração?')) {
      return;
    }

    setRenewingId(instanceId);
    setRenewError(null);

    try {
      await integracaoCanalService.renewToken(instanceId);
      alert('Token renovado com sucesso!');
      setRenewError(null);
    } catch (err) {
      console.error('Erro ao renovar token:', err);
      alert(`Erro ao renovar token: ${err.message || 'Tente novamente'}`);
      setRenewError(err.message);
    } finally {
      setRenewingId(null);
    }
  }

  return (
    <Card className="border-2 hover:shadow-lg transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {getPlatformIcon(plataforma) ? (
              <img
                src={getPlatformIcon(plataforma)}
                alt={plataforma}
                className="w-10 h-10 object-contain"
              />
            ) : (
              <div className={`w-10 h-10 rounded-lg ${getPlatformColor(plataforma)} flex items-center justify-center`}>
                <Package className="w-6 h-6 text-white" />
              </div>
            )}
            <div>
              <CardTitle className="text-lg capitalize flex items-center gap-2">
                {plataforma}
                {integracaoAtiva && (
                  <Badge variant="secondary" className="text-xs">
                    <CheckCircle2 className="w-3 h-3 mr-1 text-green-600" />
                    Integrada
                  </Badge>
                )}
                {/* Botão Renovar Token - Apenas para Shopee */}
                {plataforma.toLowerCase() === 'shopee' && integracaoAtiva && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleRenewToken(integracaoAtiva.id)}
                    disabled={renewingId === integracaoAtiva.id}
                    className="h-6 text-xs"
                  >
                    {renewingId === integracaoAtiva.id ? (
                      <><RefreshCw className="w-3 h-3 mr-1 animate-spin" /> Renovando...</>
                    ) : (
                      <><RefreshCw className="w-3 h-3 mr-1" /> Renovar Token</>
                    )}
                  </Button>
                )}
                {renewError && plataforma.toLowerCase() === 'shopee' && (
                  <Badge variant="destructive" className="text-xs">
                    <AlertCircle className="w-3 h-3 mr-1" />
                    Erro no token
                  </Badge>
                )}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {totalVinculos} {totalVinculos === 1 ? 'vínculo' : 'vínculos'} • {vinculosAtivos} ativos
              </p>
              {vinculosIncompletos > 0 && (
                <Tooltip>
                  <TooltipTrigger>
                    <p className="text-xs text-amber-600 flex items-center gap-1 mt-1 cursor-help">
                      <AlertCircle className="w-3 h-3" />
                      {vinculosIncompletos} incompleto(s)
                    </p>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="text-xs">
                      <strong>Vínculos incompletos</strong> faltam uma ou ambas as integrações:
                    </p>
                    <ul className="text-xs mt-1 list-disc list-inside">
                      <li>Integração Bling (ERP)</li>
                      <li>Integração Marketplace</li>
                    </ul>
                    <p className="text-xs mt-2 text-muted-foreground">
                      Clique em "Adicionar Vínculo" para completar.
                    </p>
                  </TooltipContent>
                </Tooltip>
              )}
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onAddVinculo(plataforma)}
            className="gap-1"
          >
            <Link className="w-4 h-4" />
            Adicionar Vínculo
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {Object.entries(vinculosPorCanal).map(([canalNome, dados]) => (
          <div key={canalNome} className="mb-4 last:mb-0">
            <div className="flex items-center justify-between mb-2 p-2 bg-muted/50 rounded-md">
              <div className="flex items-center gap-2">
                <Building2 className="w-4 h-4 text-muted-foreground" />
                <span className="font-medium text-sm">{canalNome}</span>
                {!dados.canal_ativo && (
                  <Badge variant="destructive" className="text-xs">
                    Inativo
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs">
                  <Link className="w-3 h-3 mr-1" />
                  {dados.vinculos.length} vínculo(s)
                </Badge>
              </div>
            </div>
            <LojaVinculoTable
              vinculos={dados.vinculos}
              integracoes={integracoes}
              onEdit={onEditVinculo}
              onDelete={onDeleteVinculo}
            />
          </div>
        ))}

        {vinculos.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            <Package className="w-12 h-12 mx-auto mb-2 opacity-20" />
            <p className="text-sm">Nenhum vínculo configurado</p>
            <p className="text-xs">Clique em "Adicionar Vínculo" para configurar</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
