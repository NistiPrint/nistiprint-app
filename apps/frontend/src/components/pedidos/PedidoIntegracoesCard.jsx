import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Link2, ExternalLink, Copy } from 'lucide-react';
import { toast } from 'sonner';

/**
 * Card de integrações vinculadas ao pedido
 */
export default function PedidoIntegracoesCard({ integracoes }) {
  const handleCopyId = (id, plataforma) => {
    navigator.clipboard.writeText(id);
    toast.success(`ID da ${plataforma} copiado!`);
  };

  const handleOpenMarketplace = (plataforma, id) => {
    // Futuro: abrir link direto
    toast.info(`Abrir ${plataforma}: ${id}`);
  };

  if (!integracoes || integracoes.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Link2 className="w-5 h-5" />
            Integrações Vinculadas
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-center py-8">
            Nenhuma integração vinculada
          </p>
        </CardContent>
      </Card>
    );
  }

  const getPlatformBadgeStyle = (plataforma) => {
    const styles = {
      BLING: { bg: 'bg-orange-100', text: 'text-orange-800', border: 'border-orange-200' },
      SHOPEE: { bg: 'bg-orange-50', text: 'text-orange-700', border: 'border-orange-200' },
      AMAZON: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
      MERCADOLIVRE: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
      SHEIN: { bg: 'bg-black', text: 'text-white', border: 'border-gray-200' }
    };
    return styles[plataforma?.toUpperCase()] || { bg: 'bg-gray-100', text: 'text-gray-800', border: 'border-gray-200' };
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Link2 className="w-5 h-5" />
          Integrações Vinculadas
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {integracoes.map((integracao, index) => {
            const style = getPlatformBadgeStyle(integracao.plataforma);
            return (
              <div 
                key={integracao.id || index}
                className="flex items-center justify-between p-3 rounded-lg border bg-muted/30"
              >
                <div className="flex items-center gap-3">
                  <Badge 
                    variant="outline" 
                    className={`${style.bg} ${style.text} ${style.border} text-sm`}
                  >
                    {integracao.plataforma}
                  </Badge>
                  <div className="flex flex-col">
                    <span className="font-mono text-sm font-medium">
                      {integracao.id_na_plataforma}
                    </span>
                    {integracao.status_na_plataforma && (
                      <span className="text-xs text-muted-foreground">
                        Status: {integracao.status_na_plataforma}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => handleCopyId(integracao.id_na_plataforma, integracao.plataforma)}
                  >
                    <Copy className="w-4 h-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => handleOpenMarketplace(integracao.plataforma, integracao.id_na_plataforma)}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
