import test from 'node:test';
import assert from 'node:assert/strict';
import { aplicarEdicoes, interpretarColagem, normalizarQuantidade } from './composicaoLote.js';

test('normaliza decimais sem perder precisão', () => {
  assert.equal(normalizarQuantidade('0002,500000'), '2.5');
  assert.equal(normalizarQuantidade('0,000001'), '0.000001');
  assert.equal(normalizarQuantidade('999999999,999999'), '999999999.999999');
});

test('rejeita quantidades fora dos limites', () => {
  for (const value of ['0', '-1', '1,0000001', '1000000000', 'NaN', '1e3']) {
    assert.throws(() => normalizarQuantidade(value));
  }
});

test('colagem preserva células vazias e posiciona valores', () => {
  assert.deepEqual(interpretarColagem('1\t\r\n0,5\t2\r\n', 1, 2, 3, 4), [
    { row: 1, column: 2, quantidade: '1' },
    { row: 2, column: 2, quantidade: '0.5' },
    { row: 2, column: 3, quantidade: '2' },
  ]);
});

test('rejeita colagens inválidas ou maiores que a matriz', () => {
  assert.throws(() => interpretarColagem('1\t0', 0, 0, 1, 2));
  assert.throws(() => interpretarColagem('1\t2', 0, 1, 1, 2));
});

test('registra apenas edições explícitas e mantém o estado anterior para desfazer', () => {
  const anterior = aplicarEdicoes({}, [{ produtoId: 1, componenteId: 2, acao: 'definir', quantidade: '0,5' }]);
  const seguinte = aplicarEdicoes(anterior, [{ produtoId: 1, componenteId: 3, acao: 'remover' }]);
  assert.equal(anterior['1:2'].quantidade, '0.5');
  assert.equal(anterior['1:3'], undefined);
  assert.equal(seguinte['1:3'].acao, 'remover');
  assert.deepEqual(aplicarEdicoes(seguinte, [{ produtoId: 1, componenteId: 2, acao: 'reverter' }]), { '1:3': seguinte['1:3'] });
});
