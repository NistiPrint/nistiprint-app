import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Package, 
  Link, 
  Edit2, 
  Trash2, 
  CheckCircle2, 
  XCircle,
  Building2 
} from 'lucide-react';
import LojaVinculoTable from './LojaVinculoTable';

/**
 * Card de configuração de integração por plataforma
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

  const totalVinculos = vinculos.length;
  const vinculosAtivos = vinculos.filter(v => v.is_active).length;
  const integracaoAtiva = integracoes.find(i => i.is_active);

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
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {totalVinculos} {totalVinculos === 1 ? 'vínculo' : 'vínculos'} • {vinculosAtivos} ativos
              </p>
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
