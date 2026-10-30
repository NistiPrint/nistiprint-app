import test from 'node:test';
import assert from 'node:assert/strict';
import { familyChanges } from './catalogFamily.js';

test('a prévia distingue alterações de SKU, preço e inativação explícita', () => {
  const baseline = { produto: { atributos: { variations_config: [] } }, variacoes: [
    { id: 1, sku: 'OLD', preco_venda: 10, atributos: { variation_values: { Cor: 'Azul' } } },
    { id: 2, sku: 'INATIVAR' },
  ] };
  const changes = familyChanges(baseline, [], [{ id: 1, sku: 'NEW', preco_venda: 12, variation_values: { Cor: 'Azul' } }], [2]);
  assert.deepEqual(changes, ['SKU: OLD → NEW', 'Preço de NEW: 10 → 12', 'Inativar: INATIVAR']);
});

test('omissão de variação não aparece como inativação', () => {
  assert.deepEqual(familyChanges({ variacoes: [{ id: 1, sku: 'KEEP' }] }, [], [], []), []);
});
