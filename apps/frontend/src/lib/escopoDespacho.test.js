import assert from 'node:assert/strict';
import test from 'node:test';
import { horizonteDaAba, alternarPrazo, abaDoBucketPrazo, urlDoEscopo } from './escopoDespacho.js';

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

test('o bucket do lote abre a aba que o contou', () => {
  assert.equal(abaDoBucketPrazo('atrasado'), 'hoje');
  assert.equal(abaDoBucketPrazo('sem_prazo'), 'hoje');
  assert.equal(abaDoBucketPrazo('amanha'), 'amanha');
  assert.equal(abaDoBucketPrazo('depois'), 'proximos');
});

test('o escopo leva todos os canais do lote e o singular de compatibilidade', () => {
  const url = new URL(urlDoEscopo({
    integrationId: 6, modalidadeIds: [1, 2], nomeMarketplace: 'Shopee', nomeModalidade: 'Normal',
    aba: 'amanha', incluirPronto: true,
  }), 'http://torre.local');
  assert.equal(url.pathname, '/despacho/escopo');
  assert.deepEqual(url.searchParams.getAll('modalidade_ids'), ['1', '2']);
  assert.equal(url.searchParams.get('modalidade_id'), '1');
  assert.equal(url.searchParams.get('integration_id'), '6');
  assert.equal(url.searchParams.get('aba'), 'amanha');
  assert.equal(url.searchParams.get('incluir_pronto'), 'true');
});

test('sem integracao nem pronto, esses parametros nao vao na url', () => {
  const url = new URL(urlDoEscopo({ integrationId: null, modalidadeIds: [], aba: 'hoje', incluirPronto: false }), 'http://torre.local');
  assert.equal(url.searchParams.has('integration_id'), false);
  assert.equal(url.searchParams.has('modalidade_id'), false);
  assert.equal(url.searchParams.has('incluir_pronto'), false);
});
