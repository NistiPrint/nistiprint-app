const numero = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export function resumoColetaProducao(demanda) {
  const itens = demanda?.itens || []
  const totalItens = numero(demanda?.total_itens ?? demanda?.total_quantidade)
  const total = totalItens || itens.reduce((sum, item) => sum + numero(item.quantidade), 0)
  const coletado = numero(demanda?.quantidade_coletada_total)
  const finalizado = itens.reduce((sum, item) => sum + Math.max(0, numero(item.finalizados_qtd)), 0)
  const saldoColeta = Math.max(0, total - coletado)
  const sugestao = Math.floor(Math.min(saldoColeta, Math.max(0, finalizado - coletado)))

  return { total, coletado, finalizado, saldoColeta, sugestao }
}
