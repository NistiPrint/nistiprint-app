import test from 'node:test';
import assert from 'node:assert/strict';
import { calcularRestante, formatarRestante } from './alertaTurbo.js';

test('formata a contagem regressiva de um prazo futuro', () => {
  assert.equal(calcularRestante('2026-09-21T15:01:05Z', Date.parse('2026-09-21T15:00:00Z')), 65_000);
  assert.equal(formatarRestante(65_000), '1:05');
  assert.equal(formatarRestante(3_661_000), '1h01');
});

test('identifica e formata um prazo atrasado', () => {
  assert.equal(formatarRestante(-65_000), 'atrasado há 1:05');
});

test('usa fallback textual para compromisso ausente ou invalido', () => {
  assert.equal(calcularRestante(undefined, 0), null);
  assert.equal(calcularRestante(null, 0), null);
  assert.equal(calcularRestante('data-invalida', 0), null);
  assert.equal(formatarRestante(null), 'prazo indisponível');
  assert.doesNotMatch(formatarRestante(null), /NaN/);
});
