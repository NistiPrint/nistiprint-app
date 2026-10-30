import assert from 'node:assert/strict';
import test from 'node:test';
import { visibleProducts, normalizeProduct } from './productHierarchy.js';

test('collapsed families hide children and expansion preserves one row per product', () => {
  const roots = [{ id: 1, variants: [{ id: 2, parent_id: 1 }] }, { id: 3 }];
  assert.deepEqual(visibleProducts(roots, new Set()).map(row => row.id), [1, 3]);
  assert.deepEqual(visibleProducts(roots, new Set([1])).map(row => row.id), [1, 2, 3]);
});
test('canonical child fields preserve zero prices', () => {
  assert.deepEqual(normalizeProduct({nome:'Azul',sku:'A',preco_venda:0}).price, 0);
  assert.equal(normalizeProduct({nome:'Azul'}).name, 'Azul');
});
