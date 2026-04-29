import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
    ArrowLeft,
    Copy,
    ExternalLink,
    MoreHorizontal,
    Printer,
    Share2,
    Sparkles
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

/**
 * Cabeçalho da página de detalhe do pedido
 */
export default function PedidoHeader({ 
  pedido, 
  onBack,
  onCopy,
  onPrint,
  onShare
}) {
  const navigate = useNavigate();

  const handleCopyNumero = () => {
    const texto = `${pedido.numero_pedido} (${pedido.codigo_pedido_externo})`;
    navigator.clipboard.writeText(texto);
    toast.success('Número do pedido copiado!');
    onCopy?.();
  };

  const handleCopyExterno = () => {
    navigator.clipboard.writeText(pedido.codigo_pedido_externo);
    toast.success('ID externo copiado!');
  };

  const handleOpenMarketplace = () => {
    // Futuro: abrir link direto no marketplace
    toast.info('Funcionalidade em desenvolvimento');
  };

  return (
    <div className="flex flex-col gap-4 mb-6">
      {/* Navegação */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          if (onBack) {
            onBack();
          } else {
            navigate(-1);
          }
        }}
        className="w-fit gap-2"
      >
        <ArrowLeft className="w-4 h-4" />
        Voltar
      </Button>

      {/* Título e Ações */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">
              Pedido #{pedido.numero_pedido}
            </h1>
            <Badge
              style={{
                backgroundColor: pedido.status.cor,
                color: 'white'
              }}
              className="text-sm px-3 py-1"
            >
              {pedido.status.nome}
            </Badge>
            {(pedido.is_personalizado || pedido.personalizado) && (
              <Badge variant="outline" className="text-xs px-2 py-0.5 border-purple-300 text-purple-600 bg-purple-50 flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                Personalizado
              </Badge>
            )}
          </div>
          
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="font-mono text-sm">{pedido.codigo_pedido_externo}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={handleCopyExterno}
            >
              <Copy className="w-3 h-3 mr-1" />
              Copiar ID
            </Button>
            {pedido.logistica?.canal_venda?.nome ? (
              <>
                <span>•</span>
                <Badge variant="outline" className="text-xs" style={{
                  borderColor: pedido.logistica.canal_venda.cor,
                  color: pedido.logistica.canal_venda.cor
                }}>
                  {pedido.logistica.canal_venda.nome}
                </Badge>
              </>
            ) : (
              <>
                <span>•</span>
                <Badge 
                  variant="destructive" 
                  className="text-xs bg-red-50 text-red-600 border-red-200 cursor-pointer hover:bg-red-100"
                  onClick={() => navigate('/admin/integracoes?tab=marketplace')}
                >
                  Canal Não Mapeado 
                  {pedido.cliente?.informacoes_adicionais?.bling_loja_id && 
                    ` (ID Loja: ${pedido.cliente.informacoes_adicionais.bling_loja_id})`
                  }
                </Badge>
              </>
            )}
            <span>•</span>
            <span className="text-sm">{pedido.datas?.venda 
              ? new Date(pedido.datas.venda).toLocaleDateString('pt-BR')
              : '-'
            }</span>
          </div>
        </div>

        {/* Ações */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleCopyNumero}>
            <Copy className="w-4 h-4 mr-2" />
            Copiar
          </Button>
          
          <Button variant="outline" size="sm" onClick={onPrint}>
            <Printer className="w-4 h-4 mr-2" />
            Imprimir
          </Button>
          
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleOpenMarketplace}>
                <ExternalLink className="w-4 h-4 mr-2" />
                Ver no Marketplace
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onShare}>
                <Share2 className="w-4 h-4 mr-2" />
                Compartilhar
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
}
