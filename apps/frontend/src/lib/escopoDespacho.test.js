import assert from 'node:assert/strict';
import test from 'node:test';
import { horizonteDaAba, alternarPrazo } from './escopoDespacho.js';

test('o clique abre exatamente o recorte contado pela aba', () => {
  assert.deepEqual(horizonteDaAba('amanha'), ['amanha']);
  assert.deepEqual(horizonteDaAba('proximos'), ['depois']);
  assert.deepEqual(horizonteDaAba('hoje'), ['atrasado', 'hoje', 'sem_prazo']);
});

test('ampliar o recorte e reversivel e nao envia um horizonte vazio', () => {
  const amanha = horizonteDaAba('amanha');
  assert.deepEqual(alternarPrazo(amanha, 'hoje'), ['amanha', 'hoje']);
  assert.deepEqual(alternarPrazo(['amanha', 'hoje'], 'hoje'), amanha);
  assert.deepEqual(alternarPrazo(amanha, 'amanha'), amanha);
});
