const amount = (value) => Number(value || 0)

export function summarizeProductPrint(groups) {
  const quantitiesBySource = new Map()
  const excessBySource = new Map()
  const namesByPersonalization = new Map()
  let personalized = false

  for (const group of groups) {
    personalized ||= group.key.includes('|personalizada|')
    for (const item of group.items) {
      const perUnit = amount(item.quantidade_por_unidade) || 1
      const units = amount(item.quantidade_planejada) / perUnit
      const source = item.item_pedido_id
        ? `pedido:${item.item_pedido_id}`
        : item.chave_origem?.split('|capa:')[0] || item.id
      const target = item.chave_origem?.startsWith('divergencia:') ? excessBySource : quantitiesBySource
      if (!target.has(source)) target.set(source, new Map())
      const byGroup = target.get(source)
      byGroup.set(group.key, (byGroup.get(group.key) || 0) + units)

      if (item.tipo === 'personalizada' && item.nome_personalizado) {
        personalized = true
        const key = item.personalizacao_id || item.chave_origem?.split('|capa:')[0] || item.id
        namesByPersonalization.set(key, Math.max(namesByPersonalization.get(key) || 0, units))
      }
    }
  }

  const quantity = [...quantitiesBySource.entries()].reduce(
    (total, [source, byGroup]) => total + Math.max(0, ...[...byGroup.entries()].map(
      ([group, units]) => Math.max(0, units - (excessBySource.get(source)?.get(group) || 0)),
    )), 0,
  )
  const namesIdentified = [...namesByPersonalization.values()].reduce((total, units) => total + units, 0)
  return {
    quantity,
    personalized,
    namesIdentified,
    namesPending: Math.max(0, quantity - namesIdentified),
  }
}
