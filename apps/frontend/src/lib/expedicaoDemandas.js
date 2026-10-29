export const quantity = (value) => Math.max(0, Number(value) || 0);

const availableCovers = (item) => Math.max(0, quantity(item.capas_prontas) - quantity(item.expedicao_capas_retiradas_qtd));
const availableCores = (item) => Math.max(0, quantity(item.miolos_prontos) - quantity(item.expedicao_miolos_retirados_qtd));

export function stageOf(item) {
  const total = quantity(item.qtd_total);
  const withdrawn = Math.min(quantity(item.expedicao_capas_retiradas_qtd), quantity(item.expedicao_miolos_retirados_qtd));
  if (availableCovers(item) > 0 || availableCores(item) > 0) return 'ready';
  if (total > 0 && withdrawn >= total) return 'completed';
  if (quantity(item.expedicao_capas_retiradas_qtd) > 0 || quantity(item.expedicao_miolos_retirados_qtd) > 0) return 'closing';
  return 'waiting';
}

function sortItems(a, b) {
  return (a.horario_coleta || '99:99').localeCompare(b.horario_coleta || '99:99') ||
    (a.data_entrega || '9999-12-31').localeCompare(b.data_entrega || '9999-12-31') ||
    String(a.item_id).localeCompare(String(b.item_id));
}

export function groupByDemand(items) {
  const groups = new Map();
  for (const item of [...items].sort(sortItems)) {
    const key = String(item.demanda_id);
    if (!groups.has(key)) groups.set(key, {
      id: item.demanda_id, name: item.demanda_nome || `Demanda ${item.demanda_id}`,
      deadline: item.data_entrega, collection: item.horario_coleta, priority: item.trilha,
      simulation: item.simulacao === true, items: [], total: 0, covers: 0, cores: 0, match: 0, withdrawn: 0,
      needsAction: false,
    });
    const group = groups.get(key);
    const withdrawnCovers = quantity(item.expedicao_capas_retiradas_qtd);
    const withdrawnCores = quantity(item.expedicao_miolos_retirados_qtd);
    group.items.push(item);
    item.capas_disponiveis = availableCovers(item);
    item.miolos_disponiveis = availableCores(item);
    group.total += quantity(item.qtd_total);
    group.covers += item.capas_disponiveis;
    group.cores += item.miolos_disponiveis;
    group.match += quantity(item.match_disponivel);
    group.needsAction ||= item.capas_disponiveis > 0 || item.miolos_disponiveis > 0;
    group.withdrawn += Math.min(withdrawnCovers, withdrawnCores);
  }
  return [...groups.values()];
}

export function groupByStage(items, priority = 'ALL') {
  const filtered = items.filter((item) => item && typeof item === 'object' &&
    (priority === 'ALL' || item.trilha === priority));
  return Object.fromEntries(['ready', 'closing', 'waiting', 'completed'].map((stage) => [
    stage, groupByDemand(filtered.filter((item) => stageOf(item) === stage)),
  ]));
}

export function demandsForExpedition(items, priority = 'ALL') {
  return groupByDemand(items.filter((item) => item && typeof item === 'object' &&
    (priority === 'ALL' || item.trilha === priority)));
}
