import test from 'node:test';
import assert from 'node:assert/strict';
import { agruparMiolosNaoMapeados, normalizarChaveMiolo } from './miolosNaoMapeados.js';

test('normaliza prefixo Miolo sem fundir códigos diferentes', () => {
  assert.equal(normalizarChaveMiolo('Miolo VACMNA'), 'VACMNA');
  assert.equal(normalizarChaveMiolo(' vacmna '), 'VACMNA');
  assert.notEqual(normalizarChaveMiolo('VACMNA'), normalizarChaveMiolo('VACMNO'));
});

test('agrupa miolos por demanda e soma apenas as quantidades pendentes', () => {
  const groups = agruparMiolosNaoMapeados([
    { demanda_id: 'sim-1', item_id: '1', miolo_nome: 'VACMNA', pendente: 5 },
    { demanda_id: 'sim-1', item_id: '2', miolo_nome: 'Miolo VACMNA', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '5', miolo_nome: 'VACMNA', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '6', miolo_nome: 'VACMNA', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '7', miolo_nome: 'VACMNA', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '8', miolo_nome: 'VACMNA', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '3', miolo_nome: 'VACMNO', pendente: 7 },
    { demanda_id: 'sim-2', item_id: '4', miolo_nome: 'VACMNA', pendente: 2 },
  ]);

  assert.deepEqual(groups.map(({ demanda_id, miolo_nome, pendente, quantidade_linhas }) => ({
    demanda_id, miolo_nome, pendente, quantidade_linhas,
  })), [
    { demanda_id: 'sim-1', miolo_nome: 'VACMNA', pendente: 10, quantidade_linhas: 6 },
    { demanda_id: 'sim-1', miolo_nome: 'VACMNO', pendente: 7, quantidade_linhas: 1 },
    { demanda_id: 'sim-2', miolo_nome: 'VACMNA', pendente: 2, quantidade_linhas: 1 },
  ]);
});

test('mantém linhas sem código em grupos individuais', () => {
  const groups = agruparMiolosNaoMapeados([
    { demanda_id: 'sim-1', item_id: '1', pendente: 1 },
    { demanda_id: 'sim-1', item_id: '2', pendente: 2 },
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map((group) => group.miolo_nome), [null, null]);
});
