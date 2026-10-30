const stable = value => JSON.stringify(value, Object.keys(value || {}).sort());

export function familyChanges(baseline, axes, variants, deactivateIds) {
  const changes = [];
  const oldAxes = baseline?.produto?.atributos?.variations_config || [];
  const oldByName = new Map(oldAxes.map(axis => [axis.name, axis]));
  const currentByName = new Map(axes.map(axis => [axis.name, axis]));
  for (const [name, axis] of currentByName) {
    const old = oldByName.get(name);
    if (!old) changes.push(`Adicionar eixo ${name}: ${(axis.options || []).join(', ')}`);
    else if (JSON.stringify(old.options) !== JSON.stringify(axis.options)) changes.push(`Opções de ${name}: ${(old.options || []).join(', ')} → ${(axis.options || []).join(', ')}`);
  }
  for (const name of oldByName.keys()) if (!currentByName.has(name)) changes.push(`Remover eixo ${name}`);
  const previous = new Map((baseline?.variacoes || []).map(row => [String(row.id), row]));
  for (const row of variants) {
    const old = previous.get(String(row.id ?? row.produto_id));
    if (!old) { changes.push(`Criar variação: ${row.sku}`); continue; }
    if (row.sku !== old.sku) changes.push(`SKU: ${old.sku} → ${row.sku}`);
    if (Number(row.preco_venda) !== Number(old.preco_venda)) changes.push(`Preço de ${row.sku}: ${old.preco_venda ?? 'não informado'} → ${row.preco_venda}`);
    if (stable(row.variation_values) !== stable(old.atributos?.variation_values)) changes.push(`Combinação de ${row.sku}: ${JSON.stringify(old.atributos?.variation_values || {})} → ${JSON.stringify(row.variation_values || {})}`);
  }
  for (const id of deactivateIds) changes.push(`Inativar: ${previous.get(String(id))?.sku || id}`);
  return changes;
}
