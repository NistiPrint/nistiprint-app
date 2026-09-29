import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeProductPrint } from './printPlanPresentation.js'

test('counts a product once when one PDF covers capa and contra', () => {
  const art = {
    key: 'arte-1|personalizada|jardim',
    items: [
      { item_pedido_id: 1, chave_origem: 'pendente:1|capa:arte-1', tipo: 'pendente', quantidade_planejada: 1, quantidade_por_unidade: 1 },
      { item_pedido_id: 2, chave_origem: 'pendente:2|capa:arte-1', tipo: 'pendente', quantidade_planejada: 1, quantidade_por_unidade: 1 },
    ],
  }
  const duplicate = {
    key: 'componente-pronto|personalizada|jardim',
    items: art.items.map((item) => ({ ...item, chave_origem: item.chave_origem.replace('arte-1', 'componente-pronto') })),
  }
  assert.deepEqual(summarizeProductPrint([art, duplicate]), {
    quantity: 2, personalized: true, namesIdentified: 0, namesPending: 2,
  })
})

test('deduplicates names and quantities across two PDFs of one product', () => {
  const item = {
    item_pedido_id: 3, personalizacao_id: 50, tipo: 'personalizada',
    nome_personalizado: 'Ana', quantidade_planejada: 10, quantidade_por_unidade: 1,
  }
  const groups = [
    { key: 'capa|personalizada|a', items: [{ ...item, chave_origem: 'personalizacao:50|capa:capa' }] },
    { key: 'contra|personalizada|a', items: [{ ...item, chave_origem: 'personalizacao:50|capa:contra' }] },
  ]
  assert.deepEqual(summarizeProductPrint(groups), {
    quantity: 10, personalized: true, namesIdentified: 10, namesPending: 0,
  })
})

test('shows the quantity of a product without an artwork', () => {
  const groups = [{
    key: 'sem_capa|produto-c|',
    items: [{ item_pedido_id: 4, chave_origem: 'sem_capa:4', tipo: 'pendente', quantidade_planejada: 3 }],
  }]
  assert.deepEqual(summarizeProductPrint(groups), {
    quantity: 3, personalized: false, namesIdentified: 0, namesPending: 3,
  })
})

test('does not turn names found in excess into extra product units', () => {
  const groups = [{
    key: 'arte-1|personalizada|a',
    items: [
      { item_pedido_id: 5, chave_origem: 'personalizacao:51|capa:arte-1', personalizacao_id: 51, tipo: 'personalizada', nome_personalizado: 'Ana', quantidade_planejada: 3 },
      { item_pedido_id: 5, chave_origem: 'divergencia:5|capa:arte-1', tipo: 'pendente', quantidade_planejada: 1 },
    ],
  }]
  assert.deepEqual(summarizeProductPrint(groups), {
    quantity: 2, personalized: true, namesIdentified: 3, namesPending: 0,
  })
})
