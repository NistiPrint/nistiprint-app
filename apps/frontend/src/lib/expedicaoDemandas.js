export const quantity = (value) => Math.max(0, Number(value) || 0);

export function stageOf(item) {
  const total = quantity(item.qtd_total);
  const withdrawn = Math.min(quantity(item.expedicao_capas_retiradas_qtd), quantity(item.expedicao_miolos_retirados_qtd));
  if (quantity(item.match_disponivel) > 0) return 'ready';
  if (total > 0 && withdrawn >= total) return 'completed';
  if (withdrawn > 0) return 'closing';
  return 'waiting';
}

function sortItems(a, b) {
  const priority = { URGENTE: 0, FLEX: 1, NORMAL: 2 };
  return (priority[a.trilha] ?? 3) - (priority[b.trilha] ?? 3) ||
    (a.data_entrega || '9999-12-31').localeCompare(b.data_entrega || '9999-12-31') ||
    (a.horario_coleta || '23:59').localeCompare(b.horario_coleta || '23:59') ||
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
    });
    const group = groups.get(key);
    const withdrawnCovers = quantity(item.expedicao_capas_retiradas_qtd);
    const withdrawnCores = quantity(item.expedicao_miolos_retirados_qtd);
    group.items.push(item);
    group.total += quantity(item.qtd_total);
    group.covers += Math.max(0, quantity(item.capas_prontas) - withdrawnCovers);
    group.cores += Math.max(0, quantity(item.miolos_prontos) - withdrawnCores);
    group.match += quantity(item.match_disponivel);
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
