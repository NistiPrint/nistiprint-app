import { Link } from 'react-router-dom';
import { Package } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Marcador de pedido que faz parte de um pacote.
 *
 * Um pacote do marketplace vira UM pedido no ERP e N pedidos aqui. Os irmãos
 * passam a compartilhar `numero_pedido` (o número do ERP), então sem este
 * marcador a leitura natural da tela é "duplicata" — e a reação natural a uma
 * duplicata é remover uma das linhas, o que aqui significa deixar metade da
 * caixa fora da produção.
 *
 * O marcador diz três coisas, nessa ordem de importância: são um envio só, são
 * N pedidos, e quais são os outros.
 */
export default function PacoteBadge({ irmaos = 0, irmaosIds = [], variant = 'dot' }) {
  if (!irmaos || irmaos < 1) return null;

  const total = irmaos + 1;
  const descricao = `Mesmo pacote: ${total} pedidos em um único envio e uma única nota.`;

  const conteudo = (
    <TooltipContent className="max-w-xs">
      <p>{descricao}</p>
      {irmaosIds.length > 0 && (
        <p className="mt-1 text-xs opacity-80">
          Os outros: {irmaosIds.map((id, i) => (
            <span key={id}>
              {i > 0 && ', '}
              <Link to={`/vendas/pedidos/${id}`} className="underline underline-offset-2">
                #{id}
              </Link>
            </span>
          ))}
        </p>
      )}
    </TooltipContent>
  );

  if (variant === 'inline') {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 rounded border border-sky-300 bg-sky-50 px-1.5 py-0.5 text-[11px] font-medium text-sky-800">
            <Package className="h-3 w-3" />
            Pacote · {total}
          </span>
        </TooltipTrigger>
        {conteudo}
      </Tooltip>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger>
        <Package className="h-3 w-3 text-sky-600" />
      </TooltipTrigger>
      {conteudo}
    </Tooltip>
  );
}
