export function visibleProducts(products, expanded) {
  return products.flatMap(product => [product, ...(expanded.has(product.id)
    ? (product.variants || []).map(variant => ({ ...variant, display_name: variationLabel(variant, product) }))
    : [])]);
}

export function variationLabel(variant, parent) {
  const values = variant.atributos?.variation_values || {};
  const configured = (parent.atributos?.variations_config || []).map(axis => axis.name);
  const axes = [...new Set([...configured, ...Object.keys(values)])];
  const labels = axes.map(axis => values[axis]).filter(value => typeof value === 'string' && value.trim()).map(value => value.trim());
  if (labels.length) return labels.join(' / ');

  const name = (variant.name ?? variant.nome ?? '').trim();
  const parentName = (parent.name ?? parent.nome ?? '').trim();
  if (parentName && name.toLocaleLowerCase('pt-BR').startsWith(parentName.toLocaleLowerCase('pt-BR'))) {
    const suffix = name.slice(parentName.length).replace(/^[\s—–\-:|/]+/u, '').trim();
    if (suffix) return suffix;
  }
  const suffix = name.split(/\s+[—–]\s+/u);
  return suffix.length > 1 ? suffix.slice(1).join(' / ') : name;
}

export function normalizeProduct(row) {
  return { ...row, name: row.name ?? row.nome, sku_mestre: row.sku_mestre ?? row.sku,
    material_type: row.material_type ?? row.tipo_material, price: row.price ?? row.preco_venda };
}
