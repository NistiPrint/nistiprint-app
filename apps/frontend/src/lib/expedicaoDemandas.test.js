import assert from 'node:assert/strict';
import test from 'node:test';
import { groupByStage, stageOf } from './expedicaoDemandas.js';

const item = (item_id, overrides = {}) => ({
  item_id, demanda_id: 1, demanda_nome: 'Demanda 1', trilha: 'URGENTE',
  data_entrega: '2026-10-27', qtd_total: 5, capas_prontas: 0, miolos_prontos: 0,
  expedicao_capas_retiradas_qtd: 0, expedicao_miolos_retirados_qtd: 0,
  match_disponivel: 0, ...overrides,
});

test('the same demand appears in each relevant stage without duplicating item totals', () => {
  const grouped = groupByStage([
    item(11, { capas_prontas: 5, miolos_prontos: 5, match_disponivel: 5 }),
    item(12, { capas_prontas: 5, miolos_prontos: 2, expedicao_capas_retiradas_qtd: 2, expedicao_miolos_retirados_qtd: 2 }),
    item(13, { capas_prontas: 1 }),
    item(14, { capas_prontas: 5, miolos_prontos: 5, expedicao_capas_retiradas_qtd: 5, expedicao_miolos_retirados_qtd: 5 }),
  ]);
  assert.deepEqual(Object.values(grouped).map((groups) => groups.length), [1, 1, 1, 1]);
  assert.deepEqual(Object.values(grouped).map((groups) => groups[0].items[0].item_id), [11, 12, 13, 14]);
  assert.equal(grouped.ready[0].match, 5);
  assert.equal(grouped.closing[0].withdrawn, 2);
  assert.equal(grouped.closing[0].covers, 3);
  assert.equal(grouped.completed[0].withdrawn, 5);
});

test('priority filter uses values from the consolidated API', () => {
  const grouped = groupByStage([item(11), item(12, { demanda_id: 2, trilha: 'FLEX' })], 'FLEX');
  assert.deepEqual(grouped.waiting.map((group) => group.id), [2]);
  assert.equal(stageOf(item(20, { match_disponivel: 2, expedicao_capas_retiradas_qtd: 1, expedicao_miolos_retirados_qtd: 1 })), 'ready');
});
