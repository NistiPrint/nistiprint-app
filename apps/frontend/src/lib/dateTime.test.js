import test from 'node:test';
import assert from 'node:assert/strict';
import { formatAppDateInput, formatAppDateTime } from './dateTime.js';

test('converte timestamp UTC para o horario de Sao Paulo', () => {
  const formatted = formatAppDateTime('2026-09-08T03:02:55Z');

  assert.match(formatted, /08\/09\/2026/);
  assert.match(formatted, /00:02/);
  assert.doesNotMatch(formatted, /03:02/);
});

test('agrupa mensagens na data local correta perto da meia-noite', () => {
  assert.equal(formatAppDateInput('2026-09-08T02:59:35Z'), '2026-09-07');
});
