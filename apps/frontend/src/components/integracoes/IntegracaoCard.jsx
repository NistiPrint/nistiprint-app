import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Package,
  Link,
  CheckCircle2,
  Building2,
  AlertCircle,
  HelpCircle,
  AlertTriangle,
  PlugZap
} from 'lucide-react';
import LojaVinculoTable from './LojaVinculoTable';

/**
 * Card de configuração de integração por plataforma
 * Mostra os vínculos entre canais de venda e lojas Bling.
 *
 * ⚠️ IMPORTANTE: A renovação de tokens deve ser feita na aba "Integrações",
 * não nesta tela de vínculos.
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

  // Criar mapa de integrações por ID para lookup rápido
  const integracaoMap = React.useMemo(() => {
    const map = {};
    integracoes.forEach(i => { map[i.id] = i; });
    return map;
  }, [integracoes]);

  // Analisar status de cada vínculo
  const statusAnalise = React.useMemo(() => {
    let orfaos = 0;
    let placeholders = 0;
    let incompletos = 0;
    let completos = 0;

    vinculos.forEach(v => {
      const blingInt = integracaoMap[v.bling_integration_id];
      const mpInt = integracaoMap[v.marketplace_integration_id];

      const blingOk = blingInt?.is_active && blingInt?.module_id === 'bling';
      const mpOk = mpInt?.is_active && mpInt?.module_id !== 'bling';

      const blingOrfao = v.bling_integration_id && !blingInt;
      const mpOrfao = v.marketplace_integration_id && !mpInt;
      const isPlaceholder = blingInt?.is_placeholder || mpInt?.is_placeholder;

      if (blingOrfao || mpOrfao) {
        orfaos++;
      } else if (isPlaceholder) {
        placeholders++;
      } else if (blingOk && mpOk) {
        completos++;
      } else {
        incompletos++;
      }
    });

    return { orfaos, placeholders, incompletos, completos, total: vinculos.length };
  }, [vinculos, integracaoMap]);

  // Verificar se há integração marketplace ativa
  const marketplaceIntegrations = integracoes.filter(i => i.module_id === plataforma.toLowerCase());
  const integracaoAtiva = marketplaceIntegrations.find(i => i.is_active);

  // Determinar status geral da plataforma
  const getStatusBadge = () => {
    if (statusAnalise.orfaos > 0) {
      return (
        <Badge variant="destructive" className="text-xs gap-1">
          <AlertCircle className="w-3 h-3" />
          {statusAnalise.orfaos} órfão(s)
        </Badge>
      );
    }
    if (statusAnalise.placeholders > 0) {
      return (
        <Badge variant="secondary" className="text-xs gap-1 bg-yellow-100 text-yellow-800 border-yellow-300">
          <PlugZap className="w-3 h-3" />
          {statusAnalise.placeholders} pendente(s)
        </Badge>
      );
    }
    if (statusAnalise.incompletos > 0) {
      return (
        <Badge variant="outline" className="text-xs gap-1 border-amber-500 text-amber-600">
          <AlertTriangle className="w-3 h-3" />
          {statusAnalise.incompletos} incompleto(s)
        </Badge>
      );
    }
    if (statusAnalise.completos > 0) {
      return (
        <Badge variant="secondary" className="text-xs gap-1">
          <CheckCircle2 className="w-3 h-3 mr-1 text-green-600" />
          {statusAnalise.completos} completo(s)
        </Badge>
      );
    }
    return null;
  };

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
              <CardTitle className="text-lg capitalize flex items-center gap-2 flex-wrap">
                {plataforma}
                {getStatusBadge()}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {statusAnalise.total} {statusAnalise.total === 1 ? 'vínculo' : 'vínculos'} • {statusAnalise.completos} completos
              </p>

              {/* Mensagens de alerta */}
              {statusAnalise.orfaos > 0 && (
                <Tooltip>
                  <TooltipTrigger>
                    <p className="text-xs text-red-600 flex items-center gap-1 mt-1 cursor-help">
                      <AlertCircle className="w-3 h-3" />
                      {statusAnalise.orfaos} vínculo(s) com integração inexistente
                    </p>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="text-xs">
                      <strong>Vínculos órfãos</strong> referenciam integrações que não existem mais.
                    </p>
                    <p className="text-xs mt-2 text-muted-foreground">
                      Execute o script de correção ou remova os vínculos manualmente.
                    </p>
                  </TooltipContent>
                </Tooltip>
              )}

              {statusAnalise.placeholders > 0 && (
                <Tooltip>
                  <TooltipTrigger>
                    <p className="text-xs text-yellow-600 flex items-center gap-1 mt-1 cursor-help">
                      <PlugZap className="w-3 h-3" />
                      {statusAnalise.placeholders} integração(ões) precisa(m) configuração
                    </p>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="text-xs">
                      <strong>Placeholders</strong> são integrações criadas automaticamente.
                    </p>
                    <p className="text-xs mt-2">
                      Vá para <strong>Integrações</strong> e configure cada uma.
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
