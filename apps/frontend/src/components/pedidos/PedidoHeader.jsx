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
  FileText,
  MoreHorizontal,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { formatAppDateTime } from '@/lib/dateTime';
import { getOrderTimestamps } from '@/lib/orderTimestamps';

/**
 * Cabeçalho da página de detalhe do pedido
 */
export default function PedidoHeader({
  pedido,
  onBack,
  onCopy,
  onOpenDetails,
  onOpenLogs,
  onReprocess,
  isReprocessing,
}) {
  const navigate = useNavigate();
  const timestamps = getOrderTimestamps(pedido);

  const handleCopyNumero = () => {
    const texto = `${pedido.numero_pedido} (${pedido.codigo_pedido_externo})`;
    navigator.clipboard.writeText(texto);
    toast.success('Número do pedido copiado!');
    onCopy?.();
  };

  return (
    <div className="flex flex-col gap-4 mb-6">
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

      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">
              Pedido #{pedido.numero_pedido}
            </h1>
            <Badge
              style={{
                backgroundColor: pedido.statusFormatado?.cor || '#f59e0b',
                color: 'white',
              }}
              className="text-sm px-3 py-1"
            >
              {pedido.statusFormatado?.nome || 'Pendente'}
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
            {pedido.logistica?.canal_venda?.nome ? (
              <>
                <span>•</span>
                <Badge
                  variant="outline"
                  className="text-xs"
                  style={{
                    borderColor: pedido.logistica.canal_venda.cor,
                    color: pedido.logistica.canal_venda.cor,
                  }}
                >
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
            <span className="text-sm">
              {timestamps.compra || pedido.datas?.venda
                ? `Compra: ${formatAppDateTime(timestamps.compra || pedido.datas?.venda, { fallback: String(timestamps.compra || pedido.datas?.venda) })}`
                : '-'}
            </span>
            <span>â€¢</span>
            <span className="text-sm">
              {timestamps.pagamento
                ? `Pagamento: ${formatAppDateTime(timestamps.pagamento, { fallback: String(timestamps.pagamento) })}`
                : 'Pagamento não informado'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onOpenDetails}>Mais detalhes</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={handleCopyNumero}>
                <Copy className="w-4 h-4 mr-2" />
                Copiar ID
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onOpenLogs}>
                <FileText className="w-4 h-4 mr-2" />
                Logs
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onReprocess} disabled={isReprocessing}>
                <RefreshCw className={`w-4 h-4 mr-2 ${isReprocessing ? 'animate-spin' : ''}`} />
                Reprocessar
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
}
