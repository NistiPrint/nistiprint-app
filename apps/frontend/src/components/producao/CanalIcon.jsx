import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { resolverIconeCanal } from '@/lib/canalIcons';
import { useState } from 'react';

/**
 * Icone do canal / marketplace. Sem icone conhecido (ou se a imagem falhar),
 * cai no badge com o nome do canal; com `comTooltip={false}` nao renderiza nada
 * nesse caso, para quem ja mostra o nome ao lado.
 */
function CanalIcon({
  canalNome,
  marketplaceSlug,
  marketplaceColor,
  moduleIcons,
  className = 'h-6 w-6 object-contain',
  comTooltip = true,
}) {
  const [imgError, setImgError] = useState(false);
  const iconUrl = resolverIconeCanal(canalNome, marketplaceSlug, moduleIcons);

  if (iconUrl && !imgError) {
    const imagem = (
      <img
        src={iconUrl}
        alt={canalNome || 'Origem'}
        className={className}
        onError={() => setImgError(true)}
      />
    );

    if (!comTooltip) return imagem;

    return (
      <Tooltip>
        <TooltipTrigger>{imagem}</TooltipTrigger>
        <TooltipContent>{canalNome || 'Origem'}</TooltipContent>
      </Tooltip>
    );
  }

  if (!comTooltip) return null;

  return (
    <Badge variant="outline" style={marketplaceColor ? { backgroundColor: marketplaceColor, color: '#fff' } : undefined}>
      {canalNome || 'Origem indefinida'}
    </Badge>
  );
}

export default CanalIcon;
