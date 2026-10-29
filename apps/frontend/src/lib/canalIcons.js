// Resolucao do icone de um canal de venda / marketplace.
//
// Os SVGs nao ficam neste repositorio: vem de `integration_modules.icon_url`
// (via MarketplaceService.getAvailableModules) e, para canais antigos que nunca
// passaram pelo marketplace, do mapa legado abaixo.

export const ICONES_CANAL_LEGADO = {
  shopee: 'https://app.nistiprint.com.br/assets/img/shopee.svg',
  amazon: 'https://app.nistiprint.com.br/assets/img/amazon.svg',
  mercadolivre: 'https://app.nistiprint.com.br/assets/img/mercadolivre.svg',
  shein: 'https://app.nistiprint.com.br/assets/img/shein.svg',
  magazineluiza: 'https://app.nistiprint.com.br/assets/img/magazineluiza.svg',
  kwai: 'https://app.nistiprint.com.br/assets/img/kwai.svg',
  tiktokshop: 'https://app.nistiprint.com.br/assets/img/tiktok.svg',
  lojaintegrada: 'https://app.nistiprint.com.br/assets/img/lojaintegrada.svg',
};

export function slugCanal(valor) {
  return valor ? String(valor).toLowerCase().replace(/\s+/g, '') : '';
}

/**
 * Devolve a URL do icone ou undefined. A precedencia e a mesma que a tabela de
 * pedidos sempre usou: match exato nos modulos instalados, match exato no mapa
 * legado, depois match parcial em cada um deles.
 */
export function resolverIconeCanal(canalNome, marketplaceSlug, moduleIcons) {
  const slug = slugCanal(marketplaceSlug) || slugCanal(canalNome);
  if (!slug) return undefined;

  return (
    moduleIcons?.[slug] ||
    ICONES_CANAL_LEGADO[slug] ||
    Object.entries(moduleIcons || {}).find(([chave]) => slug.includes(chave))?.[1] ||
    Object.entries(ICONES_CANAL_LEGADO).find(([chave]) => slug.includes(chave))?.[1]
  );
}
