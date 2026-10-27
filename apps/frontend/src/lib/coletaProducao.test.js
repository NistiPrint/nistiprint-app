import assert from 'node:assert/strict'
import test from 'node:test'
import { resumoColetaProducao } from './coletaProducao.js'

test('sugere finalizados ainda não coletados', () => {
  const resumo = resumoColetaProducao({
    total_itens: 300,
    quantidade_coletada_total: 100,
    itens: [{ finalizados_qtd: 180 }, { finalizados_qtd: 100 }],
  })
  assert.deepEqual(resumo, {
    total: 300, coletado: 100, finalizado: 280, saldoColeta: 200, sugestao: 180,
  })
})

test('limita a sugestão ao saldo e não sugere valor negativo', () => {
  assert.equal(resumoColetaProducao({
    total_itens: 300, quantidade_coletada_total: 280,
    itens: [{ finalizados_qtd: 300 }],
  }).sugestao, 20)
  assert.equal(resumoColetaProducao({
    total_itens: 300, quantidade_coletada_total: 280,
    itens: [{ finalizados_qtd: 270 }],
  }).sugestao, 0)
})
