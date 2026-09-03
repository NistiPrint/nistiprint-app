import test from 'node:test';
import assert from 'node:assert/strict';
import { inserirLinha, linhasParaTsv, moverLinha, totalizarLinhas } from './consolidacaoEditavel.js';

test('totaliza quantidades editadas', () => assert.equal(totalizarLinhas([{ quantidade: 2 }, { quantidade: '3' }, { quantidade: '' }]), 5));
test('serializa cinco colunas TSV com quebra final', () => {
  assert.equal(linhasParaTsv([{ descricao: 'Caneca', sku_externo: 'SKU1', variacao: '', miolo_nome: 'Branca', quantidade: 2 }]), 'Caneca\tSKU1\t\tBranca\t2\n');
});
test('insere e reordena linhas sem agrupar', () => {
  const base = [{ client_id: 'a' }, { client_id: 'b' }];
  const inserida = inserirLinha(base, 1, true);
  assert.equal(inserida.length, 3);
  assert.equal(moverLinha(inserida, 2, 0)[0].client_id, 'b');
});
